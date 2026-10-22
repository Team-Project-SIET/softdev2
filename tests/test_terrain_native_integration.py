"""Simulated external lifecycle, real transport, admission and offline replay."""

import asyncio
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
from collections import deque
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from app.simulation.openttd.admin_protocol import encode_admin_frame
from app.simulation.openttd.gamescript_transport import (
    ADMIN_GAMESCRIPT,
    GameScriptSession,
    decode_gamescript,
)
from app.simulation.openttd.supplemental_planning_facts import Region
from app.simulation.openttd.terrain_native_integration import (
    ControlledTerrainAcquisition,
    IntegrationLimits,
    SimulatedCleanup,
    SimulatedConnection,
    SimulatedRuntime,
)
from app.simulation.openttd.terrain_native_integration import (
    SimulatedBackend as BackendProtocol,
)
from app.simulation.openttd.terrain_pagination import PaginationBudget
from app.simulation.openttd.terrain_paired_evidence import verify_paired_package
from app.simulation.openttd.terrain_sweeps import (
    TerrainSweepContext,
    TerrainTwoSweep,
    TwoSweepBudget,
)
from app.simulation.openttd.tile_facts import TileFactsRequest
from tests.test_terrain_pagination import exchange
from tests.test_terrain_sweeps import context


class MemorySession(GameScriptSession):
    def __init__(self, backend):
        self.backend = backend
        self.inbound = deque()
        self.closed = False
        self.requests = []

    async def send(self, *frames):
        for frame in frames:
            self.validate_outbound(frame)
            if frame[2] == ADMIN_GAMESCRIPT:
                q = TileFactsRequest.parse(decode_gamescript(frame[3:]))
                self.requests.append(q)
                ex = exchange(q, self.backend.context.map_width, self.backend.context.map_height)
                if self.backend.problem in ("missing", "loss"):
                    continue
                if self.backend.problem in ("correlation", "order"):
                    wrong = replace(q, request_id="foreign", cursor=5)
                    ex = exchange(
                        wrong, self.backend.context.map_width, self.backend.context.map_height
                    )
                if self.backend.problem == "drift" and "-s2-" in q.request_id:
                    value = json.loads(ex.response_payload)
                    value["tiles"][0][1] = 1
                    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
                    ex = replace(ex, response_payload=raw)
                if self.backend.problem == "world":
                    self.backend.context = replace(self.backend.context, world_fingerprint="b" * 64)
                if self.backend.problem == "process":
                    self.backend.alive = False
                if self.backend.problem == "mode":
                    self.backend.mode = "REAL"
                self.inbound.append(encode_admin_frame(124, ex.response_payload + b"\0"))
                if self.backend.problem == "duplicate":
                    self.inbound.append(encode_admin_frame(124, ex.response_payload + b"\0"))
                self.backend.log += (
                    f"BRIDGE_REQUEST_RECEIVED request_id={q.request_id} "
                    "type=tile_facts_page protocol=1\n"
                    f"TILE_FACTS_READ request_id={q.request_id} "
                    f"response_json={ex.response.to_bytes().decode()}\n"
                    f"BRIDGE_RESPONSE_SENT request_id={q.request_id} "
                    "type=tile_facts_page_result status=ok protocol=1\n"
                )
            elif frame[2] == 7:
                self.inbound.append(encode_admin_frame(126, frame[3:]))

    async def receive(self, size=4096):
        if self.backend.problem == "blocked" and self.requests:
            await asyncio.Future()
        return self.inbound.popleft() if self.inbound else b""

    async def close(self, *, quit=False):
        if self.backend.problem == "close":
            raise OSError("Simulated close failure")
        self.closed = True


class SimulatedBackend:
    mode = "CONTROLLED_SIMULATED"

    def __init__(self, c, problem=None):
        self.context = c
        self.session: GameScriptSession | None = None
        self.alive = False
        self.launches = 0
        self.connections = 0
        self.disposals = 0
        self.log = ""
        self.problem = problem

    async def launch(self):
        self.launches += 1
        self.alive = True
        if self.problem == "launch":
            raise OSError("Simulated launch failure")

    async def connect(self):
        self.connections += 1
        self.session = MemorySession(self)
        if self.problem == "connect":
            raise OSError("Simulated connect failure")
        protocol = encode_admin_frame(103, b"\x03\x01" + struct.pack("<HH", 9, 64) + b"\0")
        welcome = encode_admin_frame(
            104,
            b"fixture\x0015.3\0\x01\0"
            + struct.pack(
                "<IBIHH",
                42,
                0,
                730000,
                self.context.map_width,
                self.context.map_height,
            ),
        )
        return SimulatedConnection(self.session, (protocol, welcome))

    def snapshot(self):
        buffered = 0
        if self.session is not None:
            assert isinstance(self.session, MemorySession)
            buffered = sum(len(raw) for raw in self.session.inbound)
        return SimulatedRuntime(
            "process-1",
            self.context,
            self.alive,
            self.problem != "auth",
            self.problem != "encryption",
            buffered,
        )

    async def page_evidence(self, exchange):
        if self.problem == "liveness":
            return b"No native marker\n"
        self.log += f"BRIDGE_POST_RESPONSE_ALIVE request_id={exchange.receipt.request_id}\n"
        prefix = "dbg: [script:4] [18] [I] "
        return "".join(prefix + line + "\n" for line in self.log.splitlines()).encode()

    async def cleanup(self):
        self.disposals += 1
        self.alive = False
        if self.session is not None:
            assert isinstance(self.session, MemorySession)
            self.session.closed = True
        return SimulatedCleanup(
            self.problem != "cleanup",
            True,
            True,
            self.problem != "credentials",
            (),
        )


def test_simulated_backend_session_lifecycle_through_protocol():
    backend: BackendProtocol = SimulatedBackend(context())

    async def lifecycle():
        assert backend.session is None
        await backend.launch()
        connection = await backend.connect()
        assert isinstance(connection.session, MemorySession)
        assert backend.session is connection.session
        backend.session = connection.session
        assert backend.snapshot().alive
        await connection.session.close()
        cleanup = await backend.cleanup()
        assert cleanup == SimulatedCleanup(True, True, True, True, ())
        assert connection.session.closed
        assert not backend.snapshot().alive

    asyncio.run(lifecycle())


def test_simulated_backend_supports_protocol_keyword_evidence_call():
    backend: BackendProtocol = SimulatedBackend(context())
    valid_exchange = exchange(TerrainTwoSweep(context()).requests[0])

    evidence = asyncio.run(backend.page_evidence(exchange=valid_exchange))

    assert (
        evidence
        == (
            "dbg: [script:4] [18] [I] BRIDGE_POST_RESPONSE_ALIVE "
            f"request_id={valid_exchange.receipt.request_id}\n"
        ).encode()
    )


def test_complete_controlled_lifecycle_retains_replayable_pair(tmp_path):
    backend = SimulatedBackend(context())
    acquisition = ControlledTerrainAcquisition(context())
    directory = tmp_path / "paired"
    asyncio.run(acquisition.collect(backend, directory))
    assert acquisition.state == "CLEANED"
    pinned = hashlib.sha256((directory / "package.json").read_bytes()).hexdigest()
    result = acquisition.accept(expected_descriptor_sha256=pinned)
    assert acquisition.state == "CONTROLLED_ACCEPTED"
    assert result.states == (
        "PREPARED",
        "CONNECTED",
        "SWEEP_1",
        "SWEEP_2",
        "VERIFIED",
        "CLEANED",
        "CONTROLLED_ACCEPTED",
    )
    assert [row[0] for row in result.pair.rows] == [65, 66, 67, 68, 69, 70]
    assert result.accounting.query_operations == 16
    assert result.accounting.post_auth_frames == 22
    assert result.authentication == "SIMULATED_ONLY"
    assert backend.launches == backend.connections == backend.disposals == 1
    assert not backend.alive
    assert isinstance(backend.session, MemorySession)
    assert backend.session.closed


def test_receive_buffer_cap_checks_actual_bytes_not_backend_summary(tmp_path):
    backend = SimulatedBackend(context())
    acquisition = ControlledTerrainAcquisition(
        context(), limits=IntegrationLimits(buffered_bytes=1)
    )
    with pytest.raises(ValueError, match="buffer"):
        asyncio.run(acquisition.collect(backend, tmp_path / "paired"))
    assert acquisition.state == "REJECTED"
    assert backend.disposals == 1
    assert not backend.alive


@pytest.mark.parametrize(
    "problem,reason",
    [
        ("missing", "query I/O failed"),
        ("loss", "query I/O failed"),
        ("duplicate", "Duplicate"),
        ("order", "MISMATCH"),
        ("correlation", "MISMATCH"),
        ("world", "identity"),
        ("drift", "drift"),
        ("process", "identity"),
        ("cleanup", "cleanup"),
        ("credentials", "credential"),
        ("close", "close failure"),
        ("launch", "launch failure"),
        ("connect", "connect failure"),
        ("auth", "session changed"),
        ("encryption", "session changed"),
        ("liveness", "BRIDGE_FAILURE"),
    ],
)
def test_external_failures_terminally_reject_and_dispose(tmp_path, problem, reason):
    backend = SimulatedBackend(context(), problem)
    acquisition = ControlledTerrainAcquisition(context())
    with pytest.raises(ValueError, match=reason):
        asyncio.run(acquisition.collect(backend, tmp_path / "paired"))
    assert acquisition.state == "REJECTED"
    assert backend.launches == backend.disposals == 1
    assert backend.connections <= 1
    assert not backend.alive
    assert not (tmp_path / "paired").exists()
    with pytest.raises(ValueError, match="no retry"):
        asyncio.run(acquisition.collect(backend, tmp_path / "retry"))
    assert backend.launches == 1


@pytest.mark.parametrize("sweep", [1, 2])
def test_incomplete_sweep_never_produces_evidence(tmp_path, sweep):
    class Interrupted(SimulatedBackend):
        async def page_evidence(self, exchange):
            if f"-s{sweep}-p002" in exchange.receipt.request_id:
                raise ConnectionError("Interrupted sweep")
            return await super().page_evidence(exchange)

    backend = Interrupted(context())
    acquisition = ControlledTerrainAcquisition(context())
    with pytest.raises(ValueError, match="Interrupted sweep"):
        asyncio.run(acquisition.collect(backend, tmp_path / "paired"))
    assert acquisition.state == "REJECTED"
    assert not backend.alive
    assert backend.disposals == 1


@pytest.mark.parametrize(
    "limits,per,combined,reason",
    [
        (IntegrationLimits(post_auth_frames=6), PaginationBudget(), TwoSweepBudget(), "frame"),
        (
            IntegrationLimits(simulated_stream_bytes=200),
            PaginationBudget(),
            TwoSweepBudget(),
            "byte",
        ),
        (
            IntegrationLimits(),
            PaginationBudget(page_request_bytes=1),
            TwoSweepBudget(),
            "request byte",
        ),
        (IntegrationLimits(), PaginationBudget(page_response_bytes=1), TwoSweepBudget(), "budget"),
        (
            IntegrationLimits(),
            PaginationBudget(),
            TwoSweepBudget(max_request_bytes=300),
            "request byte",
        ),
        (IntegrationLimits(), PaginationBudget(), TwoSweepBudget(max_response_bytes=300), "budget"),
        (IntegrationLimits(), PaginationBudget(), TwoSweepBudget(max_operations=15), "operation"),
    ],
)
def test_selected_resource_caps_fail_closed(tmp_path, limits, per, combined, reason):
    backend = SimulatedBackend(context())
    acquisition = ControlledTerrainAcquisition(
        context(),
        limits=limits,
        per_sweep_budget=per,
        combined_budget=combined,
    )
    with pytest.raises(ValueError, match=reason):
        asyncio.run(acquisition.collect(backend, tmp_path / "paired"))
    assert acquisition.state == "REJECTED"
    assert backend.disposals == 1
    assert not backend.alive


def test_real_wait_deadline_cancels_missing_response_and_cleans(tmp_path):
    backend = SimulatedBackend(context(), "blocked")
    acquisition = ControlledTerrainAcquisition(
        context(), limits=IntegrationLimits(page_seconds=0.001)
    )
    with pytest.raises(ValueError):
        asyncio.run(acquisition.collect(backend, tmp_path / "paired"))
    assert acquisition.state == "REJECTED"
    assert backend.disposals == 1
    assert backend.connections == 1


def test_session_deadline_uses_independent_monotonic_clock(tmp_path):
    class Clock:
        value = 0.0

        def __call__(self):
            return self.value

    clock = Clock()

    class Expiring(SimulatedBackend):
        async def page_evidence(self, exchange):
            clock.value = 6.0
            return await super().page_evidence(exchange)

    backend = Expiring(context())
    acquisition = ControlledTerrainAcquisition(
        context(),
        monotonic=clock,
        limits=IntegrationLimits(session_seconds=5),
    )
    with pytest.raises(ValueError, match="deadline expired"):
        asyncio.run(acquisition.collect(backend, tmp_path / "paired"))
    assert acquisition.state == "REJECTED"
    assert backend.disposals == 1


def test_premature_acceptance_does_not_launch_anything():
    acquisition = ControlledTerrainAcquisition(context())
    with pytest.raises(ValueError, match="Cleaned"):
        acquisition.accept(expected_descriptor_sha256="a" * 64)
    assert acquisition.state == "REJECTED"


def test_changed_evidence_with_recomputed_manifest_cannot_replace_pin(tmp_path):
    from tests.test_terrain_paired_evidence import rebuild_manifest

    acquisition = ControlledTerrainAcquisition(context())
    directory = tmp_path / "paired"
    asyncio.run(acquisition.collect(SimulatedBackend(context()), directory))
    pin = hashlib.sha256((directory / "package.json").read_bytes()).hexdigest()
    (directory / "summary.json").write_bytes(b"{}")
    rebuild_manifest(directory)
    with pytest.raises(ValueError):
        acquisition.accept(expected_descriptor_sha256=pin)
    assert acquisition.state == "REJECTED"


def test_cleanup_independent_replay_and_fresh_process(tmp_path):
    original = tmp_path / "original"
    backend = SimulatedBackend(context())
    acquisition = ControlledTerrainAcquisition(context())
    asyncio.run(acquisition.collect(backend, original))
    pin = hashlib.sha256((original / "package.json").read_bytes()).hexdigest()
    accepted = acquisition.accept(expected_descriptor_sha256=pin)
    with pytest.raises(FrozenInstanceError):
        setattr(accepted, "authentication", "REAL")
    assert accepted.authentication == "SIMULATED_ONLY"
    retained = tmp_path / "retained"
    shutil.copytree(original, retained)
    shutil.rmtree(original)
    assert verify_paired_package(retained, expected_descriptor_sha256=pin) == accepted.pair
    code = (
        "from pathlib import Path; import sys; "
        "from app.simulation.openttd.terrain_paired_evidence import verify_paired_package; "
        "r=verify_paired_package(Path(sys.argv[1]), expected_descriptor_sha256=sys.argv[2]); "
        "assert len(r.rows)==6; print('CONTROLLED replay accepted')"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code, str(retained), pin],
        cwd=tmp_path,
        env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1])),
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.stdout.strip() == "CONTROLLED replay accepted"


def test_accounting_is_derived_from_observed_frames_and_retained_exchanges(tmp_path):
    backend = SimulatedBackend(context())
    acquisition = ControlledTerrainAcquisition(context())
    path = tmp_path / "paired"
    asyncio.run(acquisition.collect(backend, path))
    result = acquisition.accept(
        expected_descriptor_sha256=hashlib.sha256((path / "package.json").read_bytes()).hexdigest()
    )
    assert result.accounting.post_auth_frames == len(result.accounting.frames) == 22
    assert result.accounting.simulated_stream_bytes == sum(
        frame.plaintext_bytes + 16 for frame in result.accounting.frames
    )
    assert (
        result.accounting.query_operations
        == sum(
            len([frame for frame in result.accounting.frames if frame.phase == phase])
            for phase in ("sweep1", "sweep2")
        )
        == 16
    )
    assert result.pair.metadata["query_operations"] == 16


@pytest.mark.parametrize("bad_mode", ["REAL", "CONTROLLED", ""])
def test_only_explicit_simulation_boundary_can_start(tmp_path, bad_mode):
    backend = SimulatedBackend(context())
    backend.mode = bad_mode
    acquisition = ControlledTerrainAcquisition(context())
    with pytest.raises(ValueError, match="simulated backend"):
        asyncio.run(acquisition.collect(backend, tmp_path / "paired"))
    assert acquisition.state == "REJECTED"
    assert backend.launches == backend.connections == backend.disposals == 0


def test_sweep_request_allowance_is_checked_before_outbound_write(tmp_path):
    backend = SimulatedBackend(context())
    acquisition = ControlledTerrainAcquisition(
        context(),
        per_sweep_budget=PaginationBudget(max_request_bytes=150),
    )
    with pytest.raises(ValueError, match="budget"):
        asyncio.run(acquisition.collect(backend, tmp_path / "paired"))
    assert isinstance(backend.session, MemorySession)
    assert len(backend.session.requests) == 1
    assert backend.disposals == 1


def test_concurrent_collection_cannot_allocate_a_second_process(tmp_path):
    async def challenge():
        started = asyncio.Event()
        release = asyncio.Event()

        class WaitingBackend(SimulatedBackend):
            async def launch(self):
                await super().launch()
                started.set()
                if self.launches == 1:
                    await release.wait()

        backend = WaitingBackend(context())
        acquisition = ControlledTerrainAcquisition(context())
        first = asyncio.create_task(acquisition.collect(backend, tmp_path / "first"))
        await started.wait()
        try:
            with pytest.raises(ValueError, match="no retry"):
                await acquisition.collect(backend, tmp_path / "second")
            assert backend.launches == 1
        finally:
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
        assert backend.disposals == 1
        assert acquisition.state == "REJECTED"

    asyncio.run(challenge())


@pytest.mark.parametrize("n", [1, 5, 6, 255, 256])
def test_bounded_regions_and_partial_last_pages(tmp_path, n):
    region = (
        Region(x=1, y=1, width=16, height=16) if n == 256 else Region(x=1, y=1, width=n, height=1)
    )
    c = TerrainSweepContext("region", "a" * 64, 512, 512, region)
    acquisition = ControlledTerrainAcquisition(c)
    backend = SimulatedBackend(c)
    path = tmp_path / "paired"
    asyncio.run(acquisition.collect(backend, path))
    pin = hashlib.sha256((path / "package.json").read_bytes()).hexdigest()
    result = acquisition.accept(expected_descriptor_sha256=pin)
    assert len(result.pair.rows) == n
    assert result.pair.metadata["pages"] == 2 * ((n + 4) // 5)
    assert result.accounting.post_auth_frames == 6 + 4 * result.pair.metadata["pages"]
    assert result.pair.sweeps[0].exchanges[-1].response.has_more is False
    assert result.pair.sweeps[1].exchanges[-1].response.has_more is False


@pytest.mark.parametrize(
    "field", ["reaped", "connection_closed", "listener_closed", "credentials_disposed"]
)
def test_every_cleanup_fact_is_mandatory(tmp_path, field):
    class FailedCleanup(SimulatedBackend):
        async def cleanup(self):
            return replace(await super().cleanup(), **{field: False})

    backend = FailedCleanup(context())
    acquisition = ControlledTerrainAcquisition(context())
    with pytest.raises(ValueError, match="cleanup"):
        asyncio.run(acquisition.collect(backend, tmp_path / "paired"))
    assert acquisition.state == "REJECTED"
    assert backend.disposals == 1
    assert not (tmp_path / "paired").exists()


def test_incorrect_caller_pin_terminally_rejects_after_cleanup(tmp_path):
    backend = SimulatedBackend(context())
    acquisition = ControlledTerrainAcquisition(context())
    asyncio.run(acquisition.collect(backend, tmp_path / "paired"))
    with pytest.raises(ValueError, match="commitment"):
        acquisition.accept(expected_descriptor_sha256="0" * 64)
    assert acquisition.state == "REJECTED"
    assert backend.disposals == 1
    with pytest.raises(ValueError, match="Cleaned"):
        acquisition.accept(expected_descriptor_sha256="a" * 64)


@pytest.mark.parametrize(
    "field,value",
    [("post_auth_frames", True), ("buffered_bytes", 65537), ("page_seconds", float("nan"))],
)
def test_invalid_resource_configuration_fails_before_process_allocation(field, value):
    with pytest.raises(ValueError):
        IntegrationLimits(**{field: value})


def test_simulation_mode_cannot_change_mid_session(tmp_path):
    backend = SimulatedBackend(context(), "mode")
    acquisition = ControlledTerrainAcquisition(context())
    with pytest.raises(ValueError, match="identity"):
        asyncio.run(acquisition.collect(backend, tmp_path / "paired"))
    assert acquisition.state == "REJECTED"
    assert backend.disposals == 1
