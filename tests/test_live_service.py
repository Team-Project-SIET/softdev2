"""T10 service selection and history contracts, without starting OpenTTD."""

import asyncio
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from test_experiments import FakeRunner, baseline_config
from test_postgres_integration import postgres_factory as postgres_factory
from test_telemetry_domain import _economy

from app.database.base import Base
from app.experiments.domain import (
    ExecutionFailure,
    ExecutionFailureCode,
    ExecutionMode,
    ExperimentConfig,
    LiveExecutionOptions,
    LiveExecutionSummary,
    Metric,
    RunStatus,
    SimulationExecutionError,
    SimulationResult,
    TelemetryStatus,
)
from app.experiments.model import (
    ExperimentMetricRecord,
    ExperimentRunRecord,
    LiveTelemetrySessionRecord,
    SimulationRunRecord,
    TelemetryObservationRecord,
)
from app.experiments.service import ExperimentService
from app.experiments.telemetry_repository import TelemetryRepository
from app.simulation.openttd.admin_observer import ObserverHealth, ObserverMeasurement, ObserverState
from app.simulation.openttd.telemetry import (
    CompanyInfoObservation,
    CompanyStatsObservation,
    GameDateObservation,
    PrimaryVehicleCounts,
    StationFacilityCounts,
)


def test_batch_default_never_touches_live_factory(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    def forbidden_live(*args, **kwargs):
        raise AssertionError("batch constructed live dependencies")

    service = ExperimentService(session_factory, FakeRunner(), live_runner_factory=forbidden_live)
    result = service.run(baseline_config(), artifact_dir=tmp_path)
    assert result.status is RunStatus.SUCCEEDED
    assert result.execution_mode is ExecutionMode.BATCH
    assert "execution_mode" not in result.model_dump()
    with session_factory() as session:
        run = session.get(ExperimentRunRecord, result.run_id)
        assert run is not None and run.execution_mode == "batch"
        assert session.get(LiveTelemetrySessionRecord, result.run_id) is None


def test_default_live_dependencies_are_inert_until_run(tmp_path: Path) -> None:
    from app.experiments.service import _default_live_runner
    from app.simulation.openttd.live_runner import LiveSimulationRunner
    from app.simulation.openttd.telemetry_processor import TelemetryProcessor

    def unused_processor(run_id: int) -> TelemetryProcessor:
        raise AssertionError("constructing live dependencies must not start telemetry")

    root = tmp_path / "artifacts"
    runner = _default_live_runner(baseline_config(), LiveExecutionOptions(), root, unused_processor)
    assert isinstance(runner, LiveSimulationRunner)
    assert runner.assets.cache_root == root / ".live-runtime-cache"
    assert runner.launch.workspace_root == root / ".live-workspaces"
    assert runner.expected_identity.seed == 17
    assert not root.exists()


@pytest.mark.parametrize(
    "reference",
    [
        "postgresql://operator:credential@localhost/save.sav",
        "run-1/final.sav\nSECRET=value",
    ],
)
def test_live_metadata_rejects_connection_strings_and_control_text(
    session_factory: sessionmaker[Session], reference: str
) -> None:
    from app.experiments.repository import ExperimentRepository

    with session_factory.begin() as session, pytest.raises(ValueError, match="sensitive"):
        ExperimentRepository().create_run(
            session,
            baseline_config(),
            datetime.now(UTC),
            execution_mode=ExecutionMode.LIVE,
            execution_metadata={"raw_save_reference": reference},
        )


def test_live_creates_history_before_runner_and_persists_one_result(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    config = baseline_config()
    options = LiveExecutionOptions(running_timeout_seconds=8)
    summary = LiveExecutionSummary(
        telemetry_status=TelemetryStatus.INCOMPLETE,
        requested_target_day=712588,
        actual_final_day=712589,
        raw_save_reference="run-1/final.sav",
        raw_save_sha256="a" * 64,
    )
    seen = []

    class LiveRunner:
        def run(
            self, config: ExperimentConfig, *, run_id: int, artifact_dir: Path
        ) -> SimulationResult:
            with session_factory() as session:
                row = session.get(ExperimentRunRecord, run_id)
                telemetry = session.get(LiveTelemetrySessionRecord, run_id)
                assert row is not None and row.status == "running"
                assert row.execution_mode == "live"
                assert telemetry is not None and telemetry.telemetry_status == "pending"
                assert row.execution_metadata == {"resolved_options": options.model_dump()}
            seen.append((run_id, artifact_dir))
            return SimulationResult(
                simulation_date=date(1950, 12, 2),
                savegame_version=302,
                metrics=(Metric(name="company_money", value=123, unit="GBP"),),
                raw_artifact_reference="run-1/parsed.json.gz",
                live_summary=summary,
            )

    def live_factory(config, resolved_options, root, processor_factory):
        assert config == baseline_config()
        assert resolved_options == options
        assert root == tmp_path
        assert callable(processor_factory)
        return LiveRunner()

    class ForbiddenBatch:
        def run(self, config, *, run_id, artifact_dir):
            raise AssertionError("live called batch runner")

    result = ExperimentService(
        session_factory, ForbiddenBatch(), live_runner_factory=live_factory
    ).run(config, artifact_dir=tmp_path, execution_mode=ExecutionMode.LIVE, live_options=options)
    assert result.status is RunStatus.SUCCEEDED
    assert result.execution_mode is ExecutionMode.LIVE
    assert result.live_summary == result.simulation.live_summary == summary
    assert seen == [(result.run_id, tmp_path / f"run-{result.run_id}")]
    with session_factory() as session:
        row = session.get(ExperimentRunRecord, result.run_id)
        telemetry = session.get(LiveTelemetrySessionRecord, result.run_id)
        assert row is not None and row.status == "succeeded"
        assert row.raw_artifact_reference == "run-1/parsed.json.gz"
        assert row.simulation is not None and row.simulation.savegame_version == 302
        assert telemetry is not None and telemetry.telemetry_status == "incomplete"
        assert session.scalar(select(ExperimentMetricRecord.value)) == 123
        assert session.scalar(select(SimulationRunRecord.id)) == row.simulation.id


@pytest.mark.parametrize(
    "code",
    [
        ExecutionFailureCode.AUTHENTICATION_FAILURE,
        ExecutionFailureCode.PROTOCOL_FAILURE,
        ExecutionFailureCode.FINALIZATION_FAILURE,
        ExecutionFailureCode.CANCELLED,
    ],
)
def test_live_typed_failure_keeps_code_and_no_final_rows(
    session_factory: sessionmaker[Session], tmp_path: Path, code: ExecutionFailureCode
) -> None:
    class FailingRunner:
        def run(self, config, *, run_id, artifact_dir):
            raise SimulationExecutionError(
                ExecutionFailure(
                    code=code,
                    message=code.value.replace("_", " "),
                    partial_artifact_reference=str(tmp_path / "partial.sav"),
                    live_summary=LiveExecutionSummary(telemetry_status=TelemetryStatus.FAILED),
                )
            )

    result = ExperimentService(
        session_factory,
        FakeRunner(),
        live_runner_factory=lambda config, options, root, processor_factory: FailingRunner(),
    ).run(baseline_config(), artifact_dir=tmp_path, execution_mode=ExecutionMode.LIVE)
    assert result.status is RunStatus.FAILED
    assert result.failure_code is code
    assert result.live_summary is not None
    with session_factory() as session:
        row = session.get(ExperimentRunRecord, result.run_id)
        telemetry = session.get(LiveTelemetrySessionRecord, result.run_id)
        assert row is not None and row.failure_code == code
        assert row.raw_artifact_reference == str(tmp_path / "partial.sav")
        assert row.simulation is None
        assert telemetry is not None and telemetry.telemetry_status == "failed"
        assert session.scalar(select(ExperimentMetricRecord.id)) is None


def test_unknown_live_failure_does_not_invent_startup_cause(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    class FailingRunner:
        def run(self, config, *, run_id, artifact_dir):
            raise RuntimeError("private path /tmp/sensitive")

    result = ExperimentService(
        session_factory,
        FakeRunner(),
        live_runner_factory=lambda config, options, root, processor_factory: FailingRunner(),
    ).run(baseline_config(), artifact_dir=tmp_path, execution_mode=ExecutionMode.LIVE)
    assert result.status is RunStatus.FAILED
    assert result.failure_code is None
    assert result.error == "live integration failure"
    with session_factory() as session:
        row = session.get(ExperimentRunRecord, result.run_id)
        assert row is not None and row.failure_code is None
        assert row.error == "live integration failure"


@pytest.mark.parametrize("failed_source", ["summary", "session"])
def test_failed_telemetry_cannot_be_committed_as_live_success(
    session_factory: sessionmaker[Session], tmp_path: Path, failed_source: str
) -> None:
    calls = 0

    class LiveRunner:
        def run(self, config, *, run_id, artifact_dir):
            nonlocal calls
            calls += 1
            if failed_source == "session":
                with session_factory.begin() as session:
                    row = session.get(LiveTelemetrySessionRecord, run_id)
                    assert row is not None
                    row.telemetry_status = TelemetryStatus.FAILED
            return SimulationResult(
                simulation_date=date(1950, 1, 2),
                savegame_version=302,
                metrics=(Metric(name="company_money", value=1, unit="GBP"),),
                live_summary=LiveExecutionSummary(
                    telemetry_status=(
                        TelemetryStatus.FAILED
                        if failed_source == "summary"
                        else TelemetryStatus.INCOMPLETE
                    ),
                    raw_save_reference="run-1/final.sav",
                ),
            )

    result = ExperimentService(
        session_factory,
        FakeRunner(),
        live_runner_factory=lambda config, options, root, factory: LiveRunner(),
    ).run(baseline_config(), artifact_dir=tmp_path, execution_mode=ExecutionMode.LIVE)
    assert calls == 1
    assert result.status is RunStatus.FAILED
    assert result.failure_code is ExecutionFailureCode.PERSISTENCE_FAILURE
    assert result.live_summary is not None
    assert result.live_summary.telemetry_status is TelemetryStatus.FAILED
    with session_factory() as session:
        run = session.get(ExperimentRunRecord, result.run_id)
        telemetry = session.get(LiveTelemetrySessionRecord, result.run_id)
        assert run is not None and run.status == "failed"
        assert run.failure_code == "persistence_failure"
        assert run.simulation is None
        assert telemetry is not None and telemetry.telemetry_status == "failed"
        assert session.scalar(select(ExperimentMetricRecord.id)) is None


def test_live_defaults_resolve_one_running_timeout_and_persist_no_secrets(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    received = []

    class FailingRunner:
        def run(self, config, *, run_id, artifact_dir):
            raise SimulationExecutionError(
                ExecutionFailure(code=ExecutionFailureCode.CANCELLED, message="cancelled")
            )

    def factory(config, options, root, processor_factory):
        received.append(options)
        return FailingRunner()

    result = ExperimentService(session_factory, FakeRunner(), live_runner_factory=factory).run(
        baseline_config(), artifact_dir=tmp_path, execution_mode=ExecutionMode.LIVE
    )
    assert result.failure_code is ExecutionFailureCode.CANCELLED
    assert len(received) == 1
    assert received[0].running_timeout_seconds == 5 * baseline_config().duration_days
    with session_factory() as session:
        run = session.get(ExperimentRunRecord, result.run_id)
        assert run is not None
        assert run.execution_metadata["resolved_options"]["running_timeout_seconds"] == 1825
        assert "password" not in str(run.execution_metadata).lower()
        assert run.failure_code == "cancelled"


def test_live_creation_failure_launches_nothing(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    from app.experiments.repository import ExperimentRepository

    class BrokenRepository(ExperimentRepository):
        def create_live_session(self, session, run_id, started_at):
            raise RuntimeError("controlled startup commit failure")

    called = False

    def live_factory(config, options, root, processor_factory):
        nonlocal called
        called = True
        raise AssertionError("must not construct a runner")

    service = ExperimentService(
        session_factory,
        FakeRunner(),
        BrokenRepository(),
        live_runner_factory=live_factory,
    )
    with pytest.raises(RuntimeError, match="startup commit failure"):
        service.run(baseline_config(), artifact_dir=tmp_path, execution_mode=ExecutionMode.LIVE)
    assert not called
    with session_factory() as session:
        assert session.scalar(select(ExperimentRunRecord.id)) is None


def test_terminal_transaction_failure_does_not_rerun_live_world(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    from app.experiments.repository import ExperimentRepository

    calls = 0

    class BrokenRepository(ExperimentRepository):
        def complete_run(self, session, run_id, result, completed_at):
            super().complete_run(session, run_id, result, completed_at)
            raise RuntimeError("controlled terminal commit failure")

    class LiveRunner:
        def run(self, config, *, run_id, artifact_dir):
            nonlocal calls
            calls += 1
            return SimulationResult(
                simulation_date=date(1950, 1, 2),
                savegame_version=302,
                metrics=(Metric(name="company_money", value=1, unit="GBP"),),
            )

    service = ExperimentService(
        session_factory,
        FakeRunner(),
        BrokenRepository(),
        live_runner_factory=lambda config, options, root, processor_factory: LiveRunner(),
    )
    with pytest.raises(RuntimeError, match="terminal commit failure"):
        service.run(baseline_config(), artifact_dir=tmp_path, execution_mode=ExecutionMode.LIVE)
    assert calls == 1
    with session_factory() as session:
        run = session.scalar(select(ExperimentRunRecord))
        assert run is not None and run.status == "running"
        assert run.simulation is None
        assert session.scalar(select(ExperimentMetricRecord.id)) is None


@pytest.mark.parametrize("complete", [False, True])
def test_postgres_live_processor_writes_before_final_simulation_row(
    postgres_factory: sessionmaker[Session], tmp_path: Path, complete: bool
) -> None:
    engine = postgres_factory.kw["bind"]
    Base.metadata.create_all(engine)
    from sqlalchemy import text

    with postgres_factory() as session:
        schema = session.scalar(text("SELECT current_schema()"))
    url = engine.url.update_query_dict({"options": f"-c search_path={schema}"})

    class LiveRunner:
        def __init__(self, processor_factory):
            self.processor_factory = processor_factory

        def run(self, config, *, run_id, artifact_dir):
            async def observe() -> None:
                processor = self.processor_factory(run_id)
                processor.start()
                processor.emit(ObserverHealth(ObserverState.CONNECTING))
                processor.emit(ObserverHealth(ObserverState.CONNECTED))
                processor.emit(ObserverHealth(ObserverState.AUTHENTICATED))
                processor.emit(ObserverMeasurement(GameDateObservation(game_day=712223)))
                if complete:
                    processor.emit(
                        ObserverMeasurement(
                            CompanyInfoObservation(
                                company_id=2,
                                name="Controlled company",
                                manager="Manager",
                                colour=1,
                                password_protected=False,
                                inaugurated_year=1950,
                                is_ai=True,
                                bankruptcy_quarters=0,
                                share_owners=(255, 255, 255, 255),
                            )
                        )
                    )
                    processor.emit(ObserverMeasurement(_economy()))
                    processor.emit(
                        ObserverMeasurement(
                            CompanyStatsObservation(
                                company_id=2,
                                primary_vehicles=PrimaryVehicleCounts(
                                    train=0, lorry=1, bus=0, plane=0, ship=0
                                ),
                                station_facilities=StationFacilityCounts(
                                    train_station=0,
                                    lorry_station=1,
                                    bus_stop=0,
                                    airport_or_heliport=0,
                                    harbour=0,
                                ),
                            )
                        )
                    )
                await processor.close()

            asyncio.run(observe())
            with postgres_factory() as session:
                run = session.get(ExperimentRunRecord, run_id)
                live = session.get(LiveTelemetrySessionRecord, run_id)
                assert run is not None and run.simulation is None
                assert live is not None and live.received_count == (5 if complete else 2)
                kinds = [
                    kind
                    for (kind,) in session.execute(
                        select(TelemetryObservationRecord.kind)
                        .where(TelemetryObservationRecord.experiment_run_id == run_id)
                        .order_by(TelemetryObservationRecord.sequence)
                    )
                ]
                assert kinds[:2] == ["diagnostic", "date"]
                assert len(kinds) == live.received_count
            return SimulationResult(
                simulation_date=date(1950, 1, 2),
                savegame_version=302,
                metrics=(Metric(name="company_money", value=42, unit="GBP"),),
                live_summary=LiveExecutionSummary(telemetry_status=TelemetryStatus.INCOMPLETE),
            )

    service = ExperimentService(
        postgres_factory,
        FakeRunner(),
        live_runner_factory=lambda config, options, root, factory: LiveRunner(factory),
        telemetry_store_factory=lambda: TelemetryRepository(url),
    )
    result = service.run(
        baseline_config(), artifact_dir=tmp_path, execution_mode=ExecutionMode.LIVE
    )
    assert result.status is RunStatus.SUCCEEDED
    assert result.live_summary is not None
    status = TelemetryStatus.COMPLETE if complete else TelemetryStatus.INCOMPLETE
    assert result.live_summary.telemetry_status is status
    assert (
        result.live_summary.received_count
        == result.live_summary.persisted_count
        == (5 if complete else 2)
    )
    with postgres_factory() as session:
        run = session.get(ExperimentRunRecord, result.run_id)
        live = session.get(LiveTelemetrySessionRecord, result.run_id)
        assert run is not None and run.simulation is not None
        assert live is not None and live.telemetry_status == status
        assert live.final_persisted_sequence == (5 if complete else 2)
        assert session.scalar(select(ExperimentMetricRecord.value)) == 42


def test_postgres_failed_live_run_retains_observations_without_final_metrics(
    postgres_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    from sqlalchemy import text

    engine = postgres_factory.kw["bind"]
    Base.metadata.create_all(engine)
    with postgres_factory() as session:
        schema = session.scalar(text("SELECT current_schema()"))
    url = engine.url.update_query_dict({"options": f"-c search_path={schema}"})

    class FailingRunner:
        def __init__(self, processor_factory):
            self.processor_factory = processor_factory

        def run(self, config, *, run_id, artifact_dir):
            async def observe() -> None:
                processor = self.processor_factory(run_id)
                processor.start()
                processor.emit(ObserverHealth(ObserverState.CONNECTING))
                processor.emit(ObserverHealth(ObserverState.CONNECTED))
                processor.emit(ObserverHealth(ObserverState.AUTHENTICATED))
                processor.emit(ObserverMeasurement(GameDateObservation(game_day=712223)))
                await processor.close()

            asyncio.run(observe())
            raise SimulationExecutionError(
                ExecutionFailure(
                    code=ExecutionFailureCode.FINALIZATION_FAILURE,
                    message="finalization failure",
                )
            )

    result = ExperimentService(
        postgres_factory,
        FakeRunner(),
        live_runner_factory=lambda config, options, root, factory: FailingRunner(factory),
        telemetry_store_factory=lambda: TelemetryRepository(url),
    ).run(baseline_config(), artifact_dir=tmp_path, execution_mode=ExecutionMode.LIVE)
    assert result.status is RunStatus.FAILED
    assert result.failure_code is ExecutionFailureCode.FINALIZATION_FAILURE
    with postgres_factory() as session:
        run = session.get(ExperimentRunRecord, result.run_id)
        live = session.get(LiveTelemetrySessionRecord, result.run_id)
        assert run is not None and run.simulation is None
        assert live is not None and live.telemetry_status == "failed"
        assert live.persisted_count == 2
        assert len(session.scalars(select(TelemetryObservationRecord)).all()) == 2
        assert session.scalar(select(ExperimentMetricRecord.id)) is None
