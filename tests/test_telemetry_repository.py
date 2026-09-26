"""Async telemetry persistence against an isolated real PostgreSQL schema."""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from test_experiments import baseline_config
from test_postgres_integration import postgres_factory as postgres_factory
from test_telemetry_domain import _economy

from app.database.base import Base
from app.experiments.domain import ExecutionMode
from app.experiments.model import LiveTelemetrySessionRecord
from app.experiments.repository import ExperimentRepository
from app.experiments.telemetry_repository import (
    TelemetryBatch,
    TelemetryProgress,
    TelemetryRepository,
    create_telemetry_engine,
)
from app.simulation.openttd.telemetry import TelemetryObservation

NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def telemetry_database(postgres_factory):
    engine = postgres_factory.kw["bind"]
    Base.metadata.create_all(engine)
    with postgres_factory.begin() as session:
        schema = session.scalar(text("SELECT current_schema()"))
        run_id = ExperimentRepository().create_run(
            session, baseline_config(), NOW, execution_mode=ExecutionMode.LIVE
        )
        session.add(
            LiveTelemetrySessionRecord(
                experiment_run_id=run_id, telemetry_status="pending", started_at=NOW
            )
        )
    return engine.url.update_query_dict({"options": f"-c search_path={schema}"}), run_id


def economy(run_id: int, sequence: int = 1, **changes) -> TelemetryObservation:
    return TelemetryObservation.model_validate(
        {
            "experiment_run_id": run_id,
            "sequence": sequence,
            "connection_epoch": 1,
            "received_at": NOW,
            "schema_version": 1,
            "source": "openttd_admin",
            "protocol_version": 2,
            "kind": "company_economy",
            "company_id": 2,
            "game_day": None,
            "date_context_sequence": None,
            "date_quality": "unknown",
            "payload": _economy(),
            **changes,
        }
    )


def test_async_exact_payload_and_idempotent_counter_round_trip(telemetry_database):
    url, run_id = telemetry_database

    async def exercise():
        repository = TelemetryRepository(url)
        deadline = asyncio.get_running_loop().time() + 10
        value = economy(run_id)
        batch = TelemetryBatch(
            (value,),
            TelemetryProgress(received_count=1, connection_count=1, last_observed_sequence=1),
        )
        try:
            await repository.write_batch(batch, deadline=deadline)
            await repository.write_batch(batch, deadline=deadline)
            assert await repository.read(run_id, deadline=deadline) == (value,)
            summary = await repository.summary(run_id, deadline=deadline)
            assert summary["persisted_count"] == summary["received_count"] == 1
            assert summary["final_persisted_sequence"] == 1
            assert summary["last_observed_day"] is None
            assert summary["telemetry_status"] != "complete"
        finally:
            await repository.close()

    asyncio.run(exercise())


def test_conflicting_retry_rolls_back_whole_batch_and_preserves_counters(telemetry_database):
    from app.experiments.telemetry_repository import TelemetryIntegrityError

    url, run_id = telemetry_database

    async def exercise():
        repository = TelemetryRepository(url)
        deadline = asyncio.get_running_loop().time() + 10
        first = economy(run_id)
        try:
            await repository.write_batch(
                TelemetryBatch(
                    (first,), TelemetryProgress(received_count=1, last_observed_sequence=1)
                ),
                deadline=deadline,
            )
            changed = economy(
                run_id, payload=_economy().model_copy(update={"cash_balance_gbp": -999})
            )
            with pytest.raises(TelemetryIntegrityError):
                await repository.write_batch(
                    TelemetryBatch(
                        (changed, economy(run_id, 2)),
                        TelemetryProgress(received_count=2, last_observed_sequence=2),
                    ),
                    deadline=deadline,
                )
            assert await repository.read(run_id, deadline=deadline) == (first,)
            assert (await repository.summary(run_id, deadline=deadline))["persisted_count"] == 1
        finally:
            await repository.close()

    asyncio.run(exercise())


def test_sequence_cursor_filters_repolls_and_exact_signed_values(telemetry_database):
    url, run_id = telemetry_database

    async def exercise():
        repository = TelemetryRepository(url)
        deadline = asyncio.get_running_loop().time() + 10
        first = economy(
            run_id,
            payload=_economy().model_copy(
                update={
                    "cash_balance_gbp": -(2**63),
                    "loan_balance_gbp": 2**63 - 1,
                    "admin_year_to_date_net_income_gbp": -(2**63) + 1,
                }
            ),
        )
        date_packet = TelemetryObservation.model_validate(
            {
                **first.model_dump(),
                "sequence": 2,
                "kind": "date",
                "company_id": None,
                "game_day": 712223,
                "date_quality": "packet_date",
                "payload": {"game_day": 712223},
            }
        )
        known = dict(game_day=712223, date_quality="preceding_date", date_context_sequence=2)
        values = (
            first,
            date_packet,
            economy(run_id, 3, **known),
            economy(run_id, 4, **known),
            economy(run_id, 5, connection_epoch=2),
        )
        try:
            await repository.write_batch(
                TelemetryBatch(
                    values,
                    TelemetryProgress(
                        received_count=5,
                        connection_count=2,
                        last_observed_sequence=5,
                        last_observed_day=712223,
                    ),
                ),
                deadline=deadline,
            )
            assert await repository.read(run_id, deadline=deadline) == values
            assert (
                await repository.read(run_id, after_sequence=2, limit=2, deadline=deadline)
                == values[2:4]
            )
            assert await repository.read(run_id, kind="date", deadline=deadline) == (date_packet,)
            assert await repository.read(run_id, company_id=0, deadline=deadline) == ()
            assert (
                await repository.read(run_id, after_sequence=2, company_id=2, deadline=deadline)
                == values[2:]
            )
            summary = await repository.summary(run_id, deadline=deadline)
            assert summary["connection_count"] == 2
            assert summary["last_observed_day"] == 712223
            assert summary["final_persisted_sequence"] == 5
            assert values[2].payload.completed_quarters[1].company_value_gbp == 0
            assert values[2].payload.current_quarter_cargo_may_be_saturated
        finally:
            await repository.close()

    asyncio.run(exercise())


def test_concurrent_identical_batches_are_idempotent(telemetry_database):
    url, run_id = telemetry_database

    async def exercise():
        repository = TelemetryRepository(url)
        deadline = asyncio.get_running_loop().time() + 10
        batch = TelemetryBatch(
            (economy(run_id),),
            TelemetryProgress(
                received_count=1, last_observed_sequence=1, unknown_packet_count=2, gap_count=1
            ),
        )
        try:
            await asyncio.gather(
                *(repository.write_batch(batch, deadline=deadline) for _ in range(3))
            )
            summary = await repository.summary(run_id, deadline=deadline)
            assert summary["persisted_count"] == 1
            assert summary["unknown_packet_count"] == 2
            assert summary["gap_count"] == 1
            assert summary["dropped_count"] == 0
        finally:
            await repository.close()

    asyncio.run(exercise())


def test_missing_session_and_cascade(telemetry_database, postgres_factory):
    from sqlalchemy import delete

    from app.experiments.model import ExperimentRunRecord
    from app.experiments.telemetry_repository import PermanentStorageError

    url, run_id = telemetry_database

    async def exercise():
        repository = TelemetryRepository(url)
        deadline = asyncio.get_running_loop().time() + 10
        try:
            batch = TelemetryBatch(
                (economy(run_id),), TelemetryProgress(received_count=1, last_observed_sequence=1)
            )
            await repository.write_batch(batch, deadline=deadline)
            with postgres_factory.begin() as session:
                session.execute(delete(ExperimentRunRecord).where(ExperimentRunRecord.id == run_id))
            assert await repository.read(run_id, deadline=deadline) == ()
            with pytest.raises(PermanentStorageError):
                await repository.write_batch(batch, deadline=deadline)
        finally:
            await repository.close()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "parameters",
    [
        {"limit": 0},
        {"limit": 1001},
        {"after_sequence": -1},
        {"kind": "invented"},
        {"company_id": -1},
        {"company_id": 15},
        {"limit": True},
    ],
)
def test_invalid_read_cursor_is_rejected_before_io(parameters):
    async def exercise():
        repository = TelemetryRepository("postgresql+psycopg://localhost/test")
        try:
            with pytest.raises(ValueError):
                await repository.read(
                    1, deadline=asyncio.get_running_loop().time() + 1, **parameters
                )
        finally:
            await repository.close()

    asyncio.run(exercise())


def test_native_timeout_closes_connection_invalidates_session_and_joins_task(telemetry_database):
    from sqlalchemy import event

    from app.experiments.telemetry_repository import TransientStorageError

    url, run_id = telemetry_database

    async def exercise():
        repository = TelemetryRepository(url)
        engine = repository.engine
        entered, exited = asyncio.Event(), asyncio.Event()
        drivers, invalidated = [], []

        @event.listens_for(engine.sync_engine, "connect")
        def remember(connection, record):
            drivers.append(connection.driver_connection)

        @event.listens_for(engine.sync_engine, "invalidate")
        def invalidate(connection, record, exception):
            invalidated.append(True)

        @event.listens_for(engine.sync_engine, "before_cursor_execute")
        def stall(connection, cursor, statement, parameters, context, many):
            if statement.startswith("INSERT INTO telemetry_observations"):

                async def hang(raw):
                    entered.set()
                    try:
                        await asyncio.Event().wait()
                    finally:
                        exited.set()

                connection.connection.dbapi_connection.run_async(hang)

        baseline = set(asyncio.all_tasks())
        try:
            batch = TelemetryBatch(
                (economy(run_id),), TelemetryProgress(received_count=1, last_observed_sequence=1)
            )
            started = asyncio.get_running_loop().time()
            with pytest.raises(TransientStorageError):
                await repository.write_batch(batch, deadline=started + 0.25)
            assert asyncio.get_running_loop().time() - started < 1
            assert entered.is_set() and exited.is_set()
            assert drivers and all(driver.closed for driver in drivers)
            assert invalidated
            assert set(asyncio.all_tasks()) == baseline
            event.remove(engine.sync_engine, "before_cursor_execute", stall)
            assert (
                await repository.read(run_id, deadline=asyncio.get_running_loop().time() + 2) == ()
            )
        finally:
            await repository.close()

    asyncio.run(exercise())


def test_committed_but_unacknowledged_batch_retries_without_duplicate_counters(telemetry_database):
    from app.experiments.telemetry_repository import TransientStorageError
    from app.simulation.openttd.admin_observer import (
        ObserverHealth,
        ObserverMeasurement,
        ObserverState,
    )
    from app.simulation.openttd.telemetry import GameDateObservation
    from app.simulation.openttd.telemetry_processor import TelemetryProcessor

    url, run_id = telemetry_database

    async def exercise():
        repository = TelemetryRepository(url)

        class AmbiguousReply:
            def __init__(self):
                self.attempts = []

            async def write_batch(self, batch, *, deadline):
                self.attempts.append(batch)
                await repository.write_batch(batch, deadline=deadline)
                if len(self.attempts) == 1:
                    raise TransientStorageError()

            async def close(self):
                pass  # This test owns the underlying repository to inspect it after close.

        reply = AmbiguousReply()
        processor = TelemetryProcessor(run_id, reply)
        try:
            processor.start()
            for state in (ObserverState.CONNECTED, ObserverState.AUTHENTICATED):
                processor.emit(ObserverHealth(state))
            processor.emit(ObserverMeasurement(GameDateObservation(game_day=712223)))
            processor.emit(ObserverMeasurement(_economy()))
            await processor.close()
            assert reply.attempts[0] is reply.attempts[1]
            deadline = asyncio.get_running_loop().time() + 2
            values = await repository.read(run_id, deadline=deadline)
            assert [v.sequence for v in values] == [1, 2, 3, 4]
            summary = await repository.summary(run_id, deadline=deadline)
            assert summary["persisted_count"] == summary["received_count"] == 4
            assert summary["last_observed_sequence"] == summary["final_persisted_sequence"] == 4
            assert summary["dropped_count"] == summary["gap_count"] == 0
            assert summary["telemetry_status"] == "recording"
        finally:
            await repository.close()

    asyncio.run(exercise())


def test_cancellation_during_first_connect_is_clean_and_sanitized(telemetry_database):
    from sqlalchemy import event

    url, run_id = telemetry_database

    async def exercise():
        repository = TelemetryRepository(url)
        engine = repository.engine
        entered, exited = asyncio.Event(), asyncio.Event()
        drivers = []

        @event.listens_for(engine.sync_engine, "first_connect")
        def stall(connection, record):
            drivers.append(connection.driver_connection)

            async def hang(raw):
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    exited.set()

            connection.run_async(hang)

        baseline = set(asyncio.all_tasks())
        task = asyncio.create_task(
            repository.read(run_id, deadline=asyncio.get_running_loop().time() + 10)
        )
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await repository.close()
        assert exited.is_set()
        assert drivers and all(raw.closed for raw in drivers)
        assert set(asyncio.all_tasks()) == baseline

    asyncio.run(exercise())


def test_server_side_statement_timeout_bounds_a_row_lock(telemetry_database, postgres_factory):
    from sqlalchemy import select

    from app.experiments.telemetry_repository import TransientStorageError

    url, run_id = telemetry_database

    async def exercise():
        repository = TelemetryRepository(url)
        with postgres_factory.begin() as blocker:
            blocker.scalar(
                select(LiveTelemetrySessionRecord)
                .where(LiveTelemetrySessionRecord.experiment_run_id == run_id)
                .with_for_update()
            )
            try:
                batch = TelemetryBatch(
                    (economy(run_id),),
                    TelemetryProgress(received_count=1, last_observed_sequence=1),
                )
                started = asyncio.get_running_loop().time()
                with pytest.raises(TransientStorageError):
                    await repository.write_batch(batch, deadline=started + 0.25)
                assert asyncio.get_running_loop().time() - started < 1
            finally:
                await repository.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("driver", ["postgresql", "postgresql+psycopg", "postgresql+psycopg_async"])
def test_async_engine_preserves_hostname_and_credentials(driver):
    from sqlalchemy.pool import NullPool

    async def exercise():
        engine = create_telemetry_engine(f"{driver}://user:secret@localhost/db?sslmode=prefer")
        try:
            assert engine.dialect.is_async
            assert engine.dialect.driver == "psycopg"
            assert isinstance(engine.pool, NullPool)
            assert engine.url.host == "localhost"
            assert engine.url.password == "secret"
            assert engine.url.query["sslmode"] == "prefer"
            assert not engine.echo
        finally:
            await engine.dispose()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "change",
    [
        {"received_at": datetime(2025, 1, 1, tzinfo=UTC)},
        {"connection_epoch": 2},
        {"schema_version": 2},
    ],
)
def test_identical_payload_with_conflicting_envelope_is_rejected(telemetry_database, change):
    from app.experiments.telemetry_repository import TelemetryIntegrityError

    url, run_id = telemetry_database

    async def exercise():
        repository = TelemetryRepository(url)
        try:
            deadline = asyncio.get_running_loop().time() + 3
            progress = TelemetryProgress(received_count=1, last_observed_sequence=1)
            await repository.write_batch(
                TelemetryBatch((economy(run_id),), progress), deadline=deadline
            )
            with pytest.raises(TelemetryIntegrityError):
                await repository.write_batch(
                    TelemetryBatch((economy(run_id, **change),), progress), deadline=deadline
                )
        finally:
            await repository.close()

    asyncio.run(exercise())


def test_batch_rejects_mutable_container_and_invalid_envelope():
    from pydantic import ValidationError

    progress = TelemetryProgress(received_count=1, last_observed_sequence=1)
    with pytest.raises(ValueError):
        TelemetryBatch([economy(1)], progress)
    with pytest.raises(ValidationError):
        TelemetryBatch((economy(1).model_copy(update={"company_id": 15}),), progress)


def test_repository_rejects_external_engine_without_deadline_tracking():
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    async def exercise():
        engine = create_async_engine("postgresql+psycopg://localhost/test", poolclass=NullPool)
        try:
            with pytest.raises(ValueError):
                TelemetryRepository(engine)
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_repository_close_awaits_session_cleanup(telemetry_database, monkeypatch):
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import AsyncSession

    url, run_id = telemetry_database

    async def exercise():
        repository = TelemetryRepository(url)
        engine = repository.engine
        entered, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        original = AsyncSession.invalidate

        async def delayed_invalidation(session):
            cleaning.set()
            await release.wait()
            await original(session)

        monkeypatch.setattr(AsyncSession, "invalidate", delayed_invalidation)

        @event.listens_for(engine.sync_engine, "before_cursor_execute")
        def stall(connection, cursor, statement, parameters, context, many):
            if "FROM live_telemetry_sessions" in statement:

                async def hang(raw):
                    entered.set()
                    await asyncio.Event().wait()

                connection.connection.dbapi_connection.run_async(hang)

        operation = asyncio.create_task(
            repository.summary(run_id, deadline=asyncio.get_running_loop().time() + 3)
        )
        await asyncio.wait_for(entered.wait(), 2)
        closing = asyncio.create_task(repository.close())
        try:
            await asyncio.wait_for(cleaning.wait(), 1)
            done, _ = await asyncio.wait({closing}, timeout=0.03)
            assert not done
        finally:
            release.set()
            await closing
            await asyncio.gather(operation, return_exceptions=True)
        assert operation.done()

    asyncio.run(exercise())


def test_all_measurement_payloads_and_null_zero_contexts_round_trip(telemetry_database):
    from app.simulation.openttd.admin_observer import (
        ObserverHealth,
        ObserverMeasurement,
        ObserverState,
    )
    from app.simulation.openttd.telemetry import (
        CompanyInfoObservation,
        CompanyStatsObservation,
        GameDateObservation,
    )
    from app.simulation.openttd.telemetry_processor import TelemetryProcessor

    url, run_id = telemetry_database
    info = CompanyInfoObservation(
        company_id=0,
        name="Zero",
        manager="Manager",
        colour=0,
        password_protected=False,
        inaugurated_year=1950,
        is_ai=True,
        bankruptcy_quarters=0,
        share_owners=(255, 255, 255, 255),
    )
    stats = CompanyStatsObservation(
        company_id=0,
        primary_vehicles=dict(train=1, lorry=2, bus=3, plane=4, ship=5),
        station_facilities=dict(
            train_station=6, lorry_station=7, bus_stop=8, airport_or_heliport=9, harbour=10
        ),
    )

    async def exercise():
        repository = TelemetryRepository(url)

        class OwnedByTest:
            async def write_batch(self, batch, *, deadline):
                await repository.write_batch(batch, deadline=deadline)

            async def close(self):
                pass

        processor = TelemetryProcessor(run_id, OwnedByTest())
        try:
            processor.start()
            processor.emit(ObserverHealth(ObserverState.CONNECTED))
            processor.emit(ObserverHealth(ObserverState.AUTHENTICATED))
            processor.emit(ObserverMeasurement(info))
            processor.emit(ObserverMeasurement(GameDateObservation(game_day=712223)))
            processor.emit(ObserverMeasurement(stats))
            processor.emit(ObserverMeasurement(_economy()))
            await processor.close()
            values = await repository.read(run_id, deadline=asyncio.get_running_loop().time() + 3)
            company_info = next(v for v in values if v.kind == "company_info")
            assert company_info.company_id == 0 and company_info.game_day is None
            assert company_info.payload == info
            station_stats = next(v for v in values if v.kind == "company_stats")
            assert station_stats.payload == stats
            assert station_stats.date_context_sequence == 4
            assert station_stats.game_day == 712223
            assert set(stats.primary_vehicles.model_dump()) == {
                "train",
                "lorry",
                "bus",
                "plane",
                "ship",
            }
        finally:
            await repository.close()

    asyncio.run(exercise())
