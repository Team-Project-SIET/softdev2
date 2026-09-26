"""Processor event, storage and health contracts without a simulator or database."""

import asyncio
from datetime import UTC, datetime

from test_telemetry_domain import _economy

from app.simulation.openttd.admin_observer import ObserverHealth, ObserverMeasurement, ObserverState
from app.simulation.openttd.telemetry import DateQuality, GameDateObservation, ObservationKind
from app.simulation.openttd.telemetry_processor import TelemetryProcessor


class RecordingRepository:
    def __init__(self):
        self.batches = []
        self.written = asyncio.Event()
        self.closed = False

    async def write_batch(self, batch, *, deadline):
        self.batches.append(batch)
        self.written.set()

    async def close(self):
        self.closed = True


def connect(processor):
    processor.emit(ObserverHealth(ObserverState.CONNECTING))
    processor.emit(ObserverHealth(ObserverState.CONNECTED))
    processor.emit(ObserverHealth(ObserverState.AUTHENTICATED))


def test_sequence_epoch_date_context_and_repolls_survive_pipeline():
    async def exercise():
        repository = RecordingRepository()
        processor = TelemetryProcessor(
            7, repository, utc_now=lambda: datetime(2026, 1, 1, tzinfo=UTC)
        )
        processor.start()
        connect(processor)
        processor.emit(ObserverMeasurement(_economy()))
        processor.emit(ObserverMeasurement(GameDateObservation(game_day=712223)))
        processor.emit(ObserverMeasurement(_economy()))
        processor.emit(ObserverMeasurement(_economy()))
        connect(processor)
        processor.emit(ObserverMeasurement(_economy()))
        await processor.close()
        values = [item for batch in repository.batches for item in batch.observations]
        assert [item.sequence for item in values] == list(range(1, len(values) + 1))
        companies = [item for item in values if item.kind is ObservationKind.COMPANY_ECONOMY]
        assert [item.connection_epoch for item in companies] == [1, 1, 1, 2]
        assert [item.game_day for item in companies] == [None, 712223, 712223, None]
        assert companies[0].date_quality is DateQuality.UNKNOWN
        date_packet = next(item for item in values if item.kind is ObservationKind.DATE)
        assert (
            companies[1].date_context_sequence
            == companies[2].date_context_sequence
            == date_packet.sequence
        )
        assert companies[-1].date_context_sequence is None
        assert all(item.payload == _economy() for item in companies)
        assert processor.pending_count == 0
        assert processor.fatal_health is None
        assert repository.closed

    asyncio.run(exercise())


def fill(processor, count):
    for _ in range(count):
        processor.emit(ObserverMeasurement(GameDateObservation(game_day=712223)))


def test_flush_at_100_and_remainder_on_close():
    async def exercise():
        repository = RecordingRepository()
        processor = TelemetryProcessor(7, repository)
        processor.start()
        connect(processor)  # one persisted connection diagnostic
        fill(processor, 99)
        await asyncio.wait_for(repository.written.wait(), 0.5)
        assert len(repository.batches[0].observations) == 100
        fill(processor, 3)
        await processor.close()
        assert [len(batch.observations) for batch in repository.batches] == [100, 3]

    asyncio.run(exercise())


def test_flush_after_one_second_without_more_input():
    async def exercise():
        repository = RecordingRepository()
        processor = TelemetryProcessor(7, repository)
        processor.start()
        start = asyncio.get_running_loop().time()
        connect(processor)
        fill(processor, 1)
        await asyncio.wait_for(repository.written.wait(), 2)
        assert asyncio.get_running_loop().time() - start >= 1
        assert len(repository.batches[0].observations) == 2
        await processor.close()

    asyncio.run(exercise())


def test_capacity_includes_inflight_and_health_remains_responsive():
    import pytest

    from app.simulation.openttd.telemetry_processor import (
        StorageHealthCode,
        TelemetryPipelineFailed,
    )

    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()

        class HeldRepository(RecordingRepository):
            async def write_batch(self, batch, *, deadline):
                entered.set()
                await release.wait()
                await super().write_batch(batch, deadline=deadline)

        repository = HeldRepository()
        processor = TelemetryProcessor(7, repository)
        processor.start()
        connect(processor)
        fill(processor, 99)
        await asyncio.wait_for(entered.wait(), 1)
        fill(processor, 924)
        assert processor.pending_count == 1024
        with pytest.raises(TelemetryPipelineFailed):
            fill(processor, 1)
        health = await asyncio.wait_for(processor.wait_fatal(), 0.1)
        assert health.code is StorageHealthCode.OVERLOADED
        assert health.received_count == 1024
        assert processor.progress.dropped_count == 0
        release.set()
        with pytest.raises(TelemetryPipelineFailed):
            await processor.close()
        assert sum(len(batch.observations) for batch in repository.batches) == 1024
        assert processor.pending_count == 0

    asyncio.run(exercise())


def test_retry_reuses_identical_batch_and_recovery_does_not_mark_fatal():
    from app.experiments.telemetry_repository import TransientStorageError

    async def exercise():
        class RetryRepository(RecordingRepository):
            def __init__(self):
                super().__init__()
                self.attempts = []

            async def write_batch(self, batch, *, deadline):
                self.attempts.append((batch, deadline))
                if len(self.attempts) == 1:
                    raise TransientStorageError()
                await super().write_batch(batch, deadline=deadline)

        repository = RetryRepository()
        processor = TelemetryProcessor(7, repository)
        processor.start()
        connect(processor)
        fill(processor, 99)
        await processor.close()
        assert repository.attempts[0][0] is repository.attempts[1][0]
        assert [
            item.sequence for batch in repository.batches for item in batch.observations
        ] == list(range(1, 102))
        assert processor.fatal_health is None
        assert processor.pending_count == 0

    asyncio.run(exercise())


def test_hanging_async_write_is_cancelled_and_joined_on_retry_deadline():
    import pytest

    from app.simulation.openttd.telemetry_processor import (
        StorageHealthCode,
        TelemetryPipelineFailed,
    )

    async def exercise():
        entered, cancelled = asyncio.Event(), asyncio.Event()

        class HungRepository(RecordingRepository):
            async def write_batch(self, batch, *, deadline):
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()

        repository = HungRepository()
        processor = TelemetryProcessor(7, repository, retry_budget=0.05)
        baseline = set(asyncio.all_tasks())
        processor.start()
        connect(processor)
        fill(processor, 99)
        await entered.wait()
        with pytest.raises(TelemetryPipelineFailed) as error:
            await processor.close()
        assert error.value.health.code is StorageHealthCode.RETRY_EXHAUSTED
        assert cancelled.is_set()
        assert repository.closed
        assert set(asyncio.all_tasks()) == baseline
        assert processor.pending_count >= 100

    asyncio.run(exercise())


def test_shutdown_deadline_cancels_and_joins_database_coroutine():
    import pytest

    from app.simulation.openttd.telemetry_processor import (
        StorageHealthCode,
        TelemetryPipelineFailed,
    )

    async def exercise():
        exited = asyncio.Event()

        class HungRepository(RecordingRepository):
            async def write_batch(self, batch, *, deadline):
                try:
                    await asyncio.Event().wait()
                finally:
                    exited.set()

        repository = HungRepository()
        processor = TelemetryProcessor(7, repository, flush_timeout=0.05)
        baseline = set(asyncio.all_tasks())
        processor.start()
        connect(processor)
        with pytest.raises(TelemetryPipelineFailed) as error:
            await processor.close()
        assert error.value.health.code is StorageHealthCode.FLUSH_TIMEOUT
        assert exited.is_set()
        assert repository.closed
        assert set(asyncio.all_tasks()) == baseline

    asyncio.run(exercise())


def test_transient_attempts_share_one_absolute_budget():
    import pytest

    from app.experiments.telemetry_repository import TransientStorageError
    from app.simulation.openttd.telemetry_processor import (
        StorageHealthCode,
        TelemetryPipelineFailed,
    )

    async def exercise():
        class AlwaysFailing(RecordingRepository):
            def __init__(self):
                super().__init__()
                self.attempts = []

            async def write_batch(self, batch, *, deadline):
                self.attempts.append((batch, asyncio.get_running_loop().time(), deadline))
                raise TransientStorageError()

        repository = AlwaysFailing()
        processor = TelemetryProcessor(7, repository, retry_budget=0.6)
        processor.start()
        connect(processor)
        fill(processor, 99)
        start = asyncio.get_running_loop().time()
        with pytest.raises(TelemetryPipelineFailed) as error:
            await processor.close()
        assert error.value.health.code is StorageHealthCode.RETRY_EXHAUSTED
        assert 0.6 <= asyncio.get_running_loop().time() - start < 1.5
        assert len(repository.attempts) == 2
        first, second = repository.attempts
        assert first[0] is second[0]
        assert first[2] == second[2]
        assert second[2] - second[1] < first[2] - first[1]

    asyncio.run(exercise())


def test_permanent_failure_is_not_retried_and_cancellation_leaves_no_tasks():
    import pytest

    from app.experiments.telemetry_repository import TelemetryIntegrityError
    from app.simulation.openttd.telemetry_processor import (
        StorageHealthCode,
        TelemetryPipelineFailed,
    )

    async def exercise():
        class Conflicting(RecordingRepository):
            async def write_batch(self, batch, *, deadline):
                self.batches.append(batch)
                raise TelemetryIntegrityError()

        repository = Conflicting()
        processor = TelemetryProcessor(7, repository)
        before = set(asyncio.all_tasks())
        processor.start()
        connect(processor)
        with pytest.raises(TelemetryPipelineFailed) as error:
            await processor.close()
        assert error.value.health.code is StorageHealthCode.PERMANENT_FAILURE
        assert len(repository.batches) == 1
        assert processor.pending_count > 0
        assert set(asyncio.all_tasks()) == before

    asyncio.run(exercise())


def test_unknown_packets_gaps_and_company_removal_are_ordered_diagnostics():
    from app.simulation.openttd.admin_observer import (
        CompanyLifecycleKind,
        ObserverCompanyLifecycle,
        ObserverUnknownPacket,
    )
    from app.simulation.openttd.telemetry import DiagnosticCode

    async def exercise():
        repository = RecordingRepository()
        processor = TelemetryProcessor(7, repository)
        processor.start()
        processor.emit(ObserverUnknownPacket(250, 999))
        connect(processor)
        processor.emit(ObserverCompanyLifecycle(CompanyLifecycleKind.NEW, 0))
        processor.emit(ObserverCompanyLifecycle(CompanyLifecycleKind.REMOVE, 0))
        processor.emit(ObserverHealth(ObserverState.CONNECTION_LOST))
        connect(processor)
        processor.emit(ObserverCompanyLifecycle(CompanyLifecycleKind.NEW, 0))
        await processor.close()
        values = [v for batch in repository.batches for v in batch.observations]
        assert values[0].connection_epoch == 0
        assert values[0].protocol_version is None
        assert [v.payload.code for v in values] == [
            DiagnosticCode.UNKNOWN_PACKET,
            DiagnosticCode.CONNECTION_OPENED,
            DiagnosticCode.COMPANY_NEW,
            DiagnosticCode.COMPANY_REMOVE,
            DiagnosticCode.CONNECTION_GAP,
            DiagnosticCode.CONNECTION_OPENED,
            DiagnosticCode.COMPANY_NEW,
        ]
        assert processor.progress.unknown_packet_count == processor.progress.gap_count == 1
        assert processor.progress.connection_count == 2
        assert values[3].company_id == values[6].company_id == 0

    asyncio.run(exercise())


def test_t08_has_no_sync_workers_or_simulator_dependencies():
    import ast
    from pathlib import Path

    for path in (
        Path("app/experiments/telemetry_repository.py"),
        Path("app/simulation/openttd/telemetry_processor.py"),
    ):
        tree = ast.parse(path.read_text())
        names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        names |= {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert not names & {
            "to_thread",
            "ThreadPoolExecutor",
            "run_in_executor",
            "ProcessPoolExecutor",
            "subprocess",
        }
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert not any("live_runner" in name or "prototype" in name for name in imports)
