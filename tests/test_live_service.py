"""T10 service selection and history contracts, without starting OpenTTD."""

import asyncio
import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session, sessionmaker
from test_experiments import FakeRunner, baseline_config
from test_live_runner import _Assets, _config, _fixture_result, _identity, _options, _runtime
from test_postgres_integration import postgres_factory as postgres_factory
from test_telemetry_domain import _economy

from app.database.base import Base
from app.experiments.cancellation import LiveCancellation
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


def _controlled_artifacts(artifact_dir: Path, run_id: int) -> tuple[str, LiveExecutionSummary]:
    (artifact_dir / "final.sav").write_bytes(b"controlled raw save")
    (artifact_dir / "parsed.json.gz").write_bytes(b"controlled parsed artifact")
    parsed_reference = f"run-{run_id}/parsed.json.gz"
    return parsed_reference, LiveExecutionSummary(
        telemetry_status=TelemetryStatus.INCOMPLETE,
        raw_save_reference=f"run-{run_id}/final.sav",
        parsed_artifact_reference=parsed_reference,
        raw_save_sha256=hashlib.sha256(b"controlled raw save").hexdigest(),
        parsed_artifact_sha256=hashlib.sha256(b"controlled parsed artifact").hexdigest(),
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
        raw_save_sha256=hashlib.sha256(b"controlled raw save").hexdigest(),
        parsed_artifact_reference="run-1/parsed.json.gz",
        parsed_artifact_sha256=hashlib.sha256(b"controlled parsed artifact").hexdigest(),
    )
    seen = []

    class LiveRunner:
        def run(
            self, config: ExperimentConfig, *, run_id: int, artifact_dir: Path
        ) -> SimulationResult:
            (artifact_dir / "final.sav").write_bytes(b"controlled raw save")
            (artifact_dir / "parsed.json.gz").write_bytes(b"controlled parsed artifact")
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
    assert result.live_summary == result.simulation.live_summary
    assert result.live_summary is not None
    assert result.live_summary.outcome_manifest_reference == "run-1/outcome-v1.json"
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


def test_live_service_normalizes_owned_absolute_parser_artifacts(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    calls = 0

    class AbsoluteArtifactRunner:
        def run(
            self, config: ExperimentConfig, *, run_id: int, artifact_dir: Path
        ) -> SimulationResult:
            nonlocal calls
            calls += 1
            raw = artifact_dir / "final.sav"
            parsed = artifact_dir / "parsed.json.gz"
            raw.write_bytes(b"controlled raw save")
            parsed.write_bytes(b"controlled parsed artifact")
            summary = LiveExecutionSummary(
                telemetry_status=TelemetryStatus.COMPLETE,
                raw_save_reference=str(raw.resolve()),
                parsed_artifact_reference=str(parsed.resolve()),
                raw_save_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),
                parsed_artifact_sha256=hashlib.sha256(parsed.read_bytes()).hexdigest(),
            )
            return SimulationResult(
                simulation_date=date(1950, 5, 1),
                savegame_version=302,
                metrics=(Metric(name="company_money", value=123, unit="GBP"),),
                raw_artifact_reference=str(parsed.resolve()),
                live_summary=summary,
            )

    result = ExperimentService(
        session_factory,
        FakeRunner(),
        live_runner_factory=lambda config, options, root, processor_factory: (
            AbsoluteArtifactRunner()
        ),
    ).run(baseline_config(), artifact_dir=tmp_path, execution_mode=ExecutionMode.LIVE)

    assert calls == 1
    assert result.status is RunStatus.SUCCEEDED
    assert not result.outcome_manifest_failed
    assert result.simulation is not None
    assert result.simulation.raw_artifact_reference == f"run-{result.run_id}/parsed.json.gz"
    assert result.live_summary is not None
    assert result.live_summary.raw_save_reference == f"run-{result.run_id}/final.sav"
    assert result.live_summary.parsed_artifact_reference == f"run-{result.run_id}/parsed.json.gz"
    assert (tmp_path / f"run-{result.run_id}/outcome-v1.json").is_file()
    with session_factory() as session:
        row = session.get(ExperimentRunRecord, result.run_id)
        assert row is not None and row.status == RunStatus.SUCCEEDED
        assert row.raw_artifact_reference == f"run-{result.run_id}/parsed.json.gz"
        assert row.simulation is not None


def test_live_service_normalizes_owned_absolute_partial_failure_artifact(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    class AbsolutePartialRunner:
        def run(self, config: ExperimentConfig, *, run_id: int, artifact_dir: Path):
            partial = artifact_dir / "partial.sav"
            partial.write_bytes(b"controlled partial")
            raise SimulationExecutionError(
                ExecutionFailure(
                    code=ExecutionFailureCode.TIMEOUT,
                    message="timeout",
                    partial_artifact_reference=str(partial.resolve()),
                    live_summary=LiveExecutionSummary(
                        telemetry_status=TelemetryStatus.INCOMPLETE,
                        raw_save_reference=str(partial.resolve()),
                    ),
                )
            )

    result = ExperimentService(
        session_factory,
        FakeRunner(),
        live_runner_factory=lambda config, options, root, processor_factory: (
            AbsolutePartialRunner()
        ),
    ).run(baseline_config(), artifact_dir=tmp_path, execution_mode=ExecutionMode.LIVE)

    assert result.status is RunStatus.FAILED
    assert result.failure_code is ExecutionFailureCode.TIMEOUT
    assert not result.outcome_manifest_failed
    assert result.live_summary is not None
    assert result.live_summary.raw_save_reference == f"run-{result.run_id}/partial.sav"
    manifest = json.loads((tmp_path / f"run-{result.run_id}/outcome-v1.json").read_text())
    assert manifest["partial_artifact_reference"] == f"run-{result.run_id}/partial.sav"
    assert manifest["failure_code"] == ExecutionFailureCode.TIMEOUT
    with session_factory() as session:
        row = session.get(ExperimentRunRecord, result.run_id)
        assert row is not None and row.status == RunStatus.FAILED
        assert row.raw_artifact_reference == f"run-{result.run_id}/partial.sav"


@pytest.mark.parametrize(
    "code",
    [
        ExecutionFailureCode.AUTHENTICATION_FAILURE,
        ExecutionFailureCode.PROTOCOL_FAILURE,
        ExecutionFailureCode.FINALIZATION_FAILURE,
        ExecutionFailureCode.CANCELLED,
        ExecutionFailureCode.TIMEOUT,
        ExecutionFailureCode.UNEXPECTED_SHUTDOWN,
    ],
)
def test_live_typed_failure_keeps_code_and_no_final_rows(
    session_factory: sessionmaker[Session], tmp_path: Path, code: ExecutionFailureCode
) -> None:
    class FailingRunner:
        def run(self, config, *, run_id, artifact_dir):
            (artifact_dir / "partial.sav").write_bytes(b"controlled partial")
            raise SimulationExecutionError(
                ExecutionFailure(
                    code=code,
                    message=code.value.replace("_", " "),
                    partial_artifact_reference=f"run-{run_id}/partial.sav",
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
        assert row.raw_artifact_reference == f"run-{result.run_id}/partial.sav"
        assert row.simulation is None
        assert telemetry is not None and telemetry.telemetry_status == "failed"
        assert session.scalar(select(ExperimentMetricRecord.id)) is None


def test_sigterm_cancellation_persists_only_sanitized_signal_metadata(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    cancellation = LiveCancellation()
    cancellation.request("SIGTERM")

    class CancelledRunner:
        def run(self, config, *, run_id, artifact_dir):
            raise SimulationExecutionError(
                ExecutionFailure(code=ExecutionFailureCode.CANCELLED, message="cancelled")
            )

    result = ExperimentService(
        session_factory,
        FakeRunner(),
        live_runner_factory=lambda config, options, root, factory: CancelledRunner(),
        live_cancellation=cancellation,
    ).run(baseline_config(), artifact_dir=tmp_path, execution_mode=ExecutionMode.LIVE)
    assert result.status is RunStatus.FAILED
    assert result.failure_code is ExecutionFailureCode.CANCELLED
    with session_factory() as session:
        row = session.get(ExperimentRunRecord, result.run_id)
        assert row is not None
        assert row.failure_code == ExecutionFailureCode.CANCELLED
        assert row.execution_metadata is not None
        assert row.execution_metadata["termination_signal"] == "SIGTERM"
        assert row.simulation is None


def test_cancellation_observed_after_runner_result_cannot_commit_success(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    cancellation = LiveCancellation()
    calls = 0

    class LateCancelledRunner:
        def run(self, config, *, run_id, artifact_dir):
            nonlocal calls
            calls += 1
            cancellation.request("SIGINT")
            return SimulationResult(
                simulation_date=date(1950, 12, 2),
                savegame_version=302,
                metrics=(Metric(name="company_money", value=123, unit="GBP"),),
                raw_artifact_reference="run-1/parsed.json.gz",
            )

    result = ExperimentService(
        session_factory,
        FakeRunner(),
        live_runner_factory=lambda config, options, root, factory: LateCancelledRunner(),
        live_cancellation=cancellation,
    ).run(baseline_config(), artifact_dir=tmp_path, execution_mode=ExecutionMode.LIVE)
    assert calls == 1
    assert result.status is RunStatus.FAILED
    assert result.failure_code is ExecutionFailureCode.CANCELLED
    with session_factory() as session:
        row = session.get(ExperimentRunRecord, result.run_id)
        assert row is not None and row.status == RunStatus.FAILED
        assert row.simulation is None
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
            (artifact_dir / "final.sav").write_bytes(b"controlled save")
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
            reference, summary = _controlled_artifacts(artifact_dir, run_id)
            return SimulationResult(
                simulation_date=date(1950, 1, 2),
                savegame_version=302,
                metrics=(Metric(name="company_money", value=1, unit="GBP"),),
                raw_artifact_reference=reference,
                live_summary=summary,
            )

    service = ExperimentService(
        session_factory,
        FakeRunner(),
        BrokenRepository(),
        live_runner_factory=lambda config, options, root, processor_factory: LiveRunner(),
    )
    result = service.run(
        baseline_config(), artifact_dir=tmp_path, execution_mode=ExecutionMode.LIVE
    )
    assert result.status is RunStatus.FAILED
    assert result.failure_code is ExecutionFailureCode.PERSISTENCE_FAILURE
    assert result.terminal_persistence_failed
    assert result.live_summary is not None
    assert result.live_summary.outcome_manifest_reference == "run-1/outcome-v1.json"
    assert (tmp_path / "run-1/outcome-v1.json").is_file()
    manifest = json.loads((tmp_path / "run-1/outcome-v1.json").read_text())
    assert manifest["intended_status"] == "succeeded"
    assert manifest["simulation"]["metrics"][0]["value"] == 1
    assert calls == 1
    with session_factory() as session:
        run = session.scalar(select(ExperimentRunRecord))
        assert run is not None and run.status == "running"
        assert run.simulation is None
        assert session.scalar(select(ExperimentMetricRecord.id)) is None


@pytest.mark.parametrize(
    "code",
    [
        ExecutionFailureCode.TIMEOUT,
        ExecutionFailureCode.CANCELLED,
        ExecutionFailureCode.UNEXPECTED_SHUTDOWN,
        ExecutionFailureCode.PERSISTENCE_FAILURE,
    ],
)
def test_failed_execution_and_failed_terminal_write_preserve_original_code(
    session_factory: sessionmaker[Session], tmp_path: Path, code: ExecutionFailureCode
) -> None:
    from app.experiments.repository import ExperimentRepository

    calls = 0

    class BrokenRepository(ExperimentRepository):
        def fail_run(self, session, run_id, error, completed_at, **kwargs):
            super().fail_run(session, run_id, error, completed_at, **kwargs)
            raise RuntimeError("controlled terminal failure")

    class FailingRunner:
        def run(self, config, *, run_id, artifact_dir):
            nonlocal calls
            calls += 1
            (artifact_dir / "partial.sav").write_bytes(b"controlled partial")
            raise SimulationExecutionError(
                ExecutionFailure(
                    code=code,
                    message=code.value.replace("_", " "),
                    partial_artifact_reference=f"run-{run_id}/partial.sav",
                    live_summary=LiveExecutionSummary(telemetry_status=TelemetryStatus.FAILED),
                )
            )

    result = ExperimentService(
        session_factory,
        FakeRunner(),
        BrokenRepository(),
        live_runner_factory=lambda config, options, root, factory: FailingRunner(),
    ).run(baseline_config(), artifact_dir=tmp_path, execution_mode=ExecutionMode.LIVE)
    assert calls == 1
    assert result.status is RunStatus.FAILED
    assert result.failure_code is code
    assert result.terminal_persistence_failed
    manifest = json.loads((tmp_path / f"run-{result.run_id}/outcome-v1.json").read_text())
    assert manifest["intended_status"] == "failed"
    assert manifest["failure_code"] == code
    assert manifest["simulation"] is None
    assert manifest["partial_artifact_reference"] == f"run-{result.run_id}/partial.sav"
    with session_factory() as session:
        run = session.get(ExperimentRunRecord, result.run_id)
        assert run is not None and run.status == RunStatus.RUNNING
        assert run.simulation is None


def test_failed_telemetry_summary_and_terminal_failure_stays_failed(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    from app.experiments.repository import ExperimentRepository

    class BrokenRepository(ExperimentRepository):
        def finish_live_session(self, session, run_id, completed_at, **kwargs):
            raise RuntimeError("controlled terminal failure")

    class LiveRunner:
        def run(self, config, *, run_id, artifact_dir):
            return SimulationResult(
                simulation_date=date(1950, 1, 2),
                savegame_version=302,
                metrics=(Metric(name="company_money", value=42, unit="GBP"),),
                live_summary=LiveExecutionSummary(telemetry_status=TelemetryStatus.FAILED),
            )

    result = ExperimentService(
        session_factory,
        FakeRunner(),
        BrokenRepository(),
        live_runner_factory=lambda config, options, root, maker: LiveRunner(),
    ).run(baseline_config(), artifact_dir=tmp_path, execution_mode=ExecutionMode.LIVE)
    assert result.status is RunStatus.FAILED
    assert result.failure_code is ExecutionFailureCode.PERSISTENCE_FAILURE
    manifest = json.loads((tmp_path / f"run-{result.run_id}/outcome-v1.json").read_text())
    assert manifest["intended_status"] == "failed"
    assert manifest["failure_code"] == "persistence_failure"
    assert manifest["simulation"] is None


def test_ambiguous_commit_is_checked_with_a_fresh_session(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    from app.experiments.repository import ExperimentRepository

    class AmbiguousSession(Session):
        pass

    @event.listens_for(AmbiguousSession, "after_commit")
    def lose_acknowledgement(session: AmbiguousSession) -> None:
        if session.info.pop("lose_terminal_ack", False):
            raise RuntimeError("commit acknowledgement lost")

    class AmbiguousRepository(ExperimentRepository):
        def complete_run(self, session, run_id, result, completed_at):
            super().complete_run(session, run_id, result, completed_at)
            session.info["lose_terminal_ack"] = True

    factory = sessionmaker(
        bind=session_factory.kw["bind"], class_=AmbiguousSession, expire_on_commit=False
    )

    class LiveRunner:
        def run(self, config, *, run_id, artifact_dir):
            reference, summary = _controlled_artifacts(artifact_dir, run_id)
            return SimulationResult(
                simulation_date=date(1950, 1, 2),
                savegame_version=302,
                metrics=(Metric(name="company_money", value=42, unit="GBP"),),
                raw_artifact_reference=reference,
                live_summary=summary,
            )

    result = ExperimentService(
        factory,
        FakeRunner(),
        AmbiguousRepository(),
        live_runner_factory=lambda config, options, root, maker: LiveRunner(),
    ).run(baseline_config(), artifact_dir=tmp_path, execution_mode=ExecutionMode.LIVE)
    assert result.status is RunStatus.SUCCEEDED
    assert result.simulation is not None
    assert result.live_summary is not None
    assert result.live_summary.outcome_manifest_reference == "run-1/outcome-v1.json"
    with factory() as session:
        row = session.get(ExperimentRunRecord, result.run_id)
        assert row is not None and row.simulation is not None


def test_ambiguous_commit_rejects_conflicting_same_day_metrics(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    class LiveRunner:
        def run(self, config, *, run_id, artifact_dir):
            reference, summary = _controlled_artifacts(artifact_dir, run_id)
            with session_factory.begin() as session:
                row = session.get(ExperimentRunRecord, run_id)
                assert row is not None and row.telemetry_session is not None
                row.status = RunStatus.SUCCEEDED
                row.telemetry_session.telemetry_status = TelemetryStatus.INCOMPLETE
                row.simulation = SimulationRunRecord(
                    simulation_date=date(1950, 1, 2),
                    savegame_version=302,
                    metrics=[ExperimentMetricRecord(name="company_money", value=999, unit="GBP")],
                )
            return SimulationResult(
                simulation_date=date(1950, 1, 2),
                savegame_version=302,
                metrics=(Metric(name="company_money", value=42, unit="GBP"),),
                raw_artifact_reference=reference,
                live_summary=summary,
            )

    result = ExperimentService(
        session_factory,
        FakeRunner(),
        live_runner_factory=lambda config, options, root, maker: LiveRunner(),
    ).run(baseline_config(), artifact_dir=tmp_path, execution_mode=ExecutionMode.LIVE)
    assert result.status is RunStatus.FAILED
    assert result.terminal_persistence_failed
    assert result.failure_code is ExecutionFailureCode.PERSISTENCE_FAILURE
    with session_factory() as session:
        row = session.get(ExperimentRunRecord, result.run_id)
        assert row is not None and row.simulation is not None
        assert row.simulation.metrics[0].value == 999


def test_terminal_db_and_manifest_failure_never_claims_durable_outcome(
    session_factory: sessionmaker[Session], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.experiments import service as service_module
    from app.experiments.repository import ExperimentRepository

    class BrokenRepository(ExperimentRepository):
        def complete_run(self, session, run_id, result, completed_at):
            raise RuntimeError("secret database failure")

    class LiveRunner:
        def run(self, config, *, run_id, artifact_dir):
            reference, summary = _controlled_artifacts(artifact_dir, run_id)
            return SimulationResult(
                simulation_date=date(1950, 1, 2),
                savegame_version=302,
                metrics=(Metric(name="company_money", value=42, unit="GBP"),),
                raw_artifact_reference=reference,
                live_summary=summary,
            )

    def fail_publication(directory, manifest):
        raise OSError("secret filesystem failure")

    monkeypatch.setattr(service_module, "publish_manifest", fail_publication)
    result = ExperimentService(
        session_factory,
        FakeRunner(),
        BrokenRepository(),
        live_runner_factory=lambda config, options, root, maker: LiveRunner(),
    ).run(baseline_config(), artifact_dir=tmp_path, execution_mode=ExecutionMode.LIVE)
    assert result.status is RunStatus.FAILED
    assert result.failure_code is ExecutionFailureCode.PERSISTENCE_FAILURE
    assert result.error == "outcome persistence unconfirmed; manifest unavailable"
    assert result.terminal_persistence_failed and result.outcome_manifest_failed
    assert result.live_summary is not None
    assert result.live_summary.outcome_manifest_reference is None
    assert not (tmp_path / "run-1/outcome-v1.json").exists()
    assert "secret" not in result.model_dump_json()


def test_manifest_write_failure_does_not_return_normal_success(
    session_factory: sessionmaker[Session], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.experiments import service as service_module

    class LiveRunner:
        def run(self, config, *, run_id, artifact_dir):
            reference, summary = _controlled_artifacts(artifact_dir, run_id)
            return SimulationResult(
                simulation_date=date(1950, 1, 2),
                savegame_version=302,
                metrics=(Metric(name="company_money", value=42, unit="GBP"),),
                raw_artifact_reference=reference,
                live_summary=summary,
            )

    def fail_publication(directory, manifest):
        raise OSError("secret filesystem failure")

    monkeypatch.setattr(service_module, "publish_manifest", fail_publication)
    result = ExperimentService(
        session_factory,
        FakeRunner(),
        live_runner_factory=lambda config, options, root, maker: LiveRunner(),
    ).run(baseline_config(), artifact_dir=tmp_path, execution_mode=ExecutionMode.LIVE)
    assert result.status is RunStatus.SUCCEEDED
    assert result.failure_code is None
    assert result.outcome_manifest_failed
    assert result.live_summary is not None
    assert result.live_summary.outcome_manifest_reference is None
    assert "secret" not in result.model_dump_json()
    with session_factory() as session:
        row = session.get(ExperimentRunRecord, result.run_id)
        assert row is not None and row.simulation is not None


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
            reference, summary = _controlled_artifacts(artifact_dir, run_id)
            return SimulationResult(
                simulation_date=date(1950, 1, 2),
                savegame_version=302,
                metrics=(Metric(name="company_money", value=42, unit="GBP"),),
                raw_artifact_reference=reference,
                live_summary=summary,
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


@pytest.mark.parametrize(
    ("mode", "connection_count", "gap_count"),
    [("normal", 1, 0), ("reconnect_success", 2, 1)],
)
def test_postgres_recovered_gap_stays_ordered_and_marks_success_incomplete(
    postgres_factory: sessionmaker[Session],
    tmp_path: Path,
    mode: str,
    connection_count: int,
    gap_count: int,
) -> None:
    from sqlalchemy import text

    from app.simulation.openttd.live_launch import LiveLaunchPreparation
    from app.simulation.openttd.live_runner import LiveSimulationRunner
    from app.simulation.openttd.telemetry import DiagnosticCode, ObservationKind

    engine = postgres_factory.kw["bind"]
    Base.metadata.create_all(engine)
    with postgres_factory() as session:
        schema = session.scalar(text("SELECT current_schema()"))
    url = engine.url.update_query_dict({"options": f"-c search_path={schema}"})
    runtime = _runtime(tmp_path, mode)

    def live_factory(config, options, root, processor_factory):
        return LiveSimulationRunner(
            _Assets(runtime, config),
            LiveLaunchPreparation(
                tmp_path / "runs", lock_root=tmp_path / "locks", port_range=(41000, 41200)
            ),
            expected_identity=_identity(),
            final_result=_fixture_result,
            options=options,
            telemetry_factory=processor_factory,
        )

    result = ExperimentService(
        postgres_factory,
        FakeRunner(),
        live_runner_factory=live_factory,
        telemetry_store_factory=lambda: TelemetryRepository(url),
    ).run(
        _config(),
        artifact_dir=tmp_path,
        execution_mode=ExecutionMode.LIVE,
        live_options=_options(
            running_timeout_seconds=4,
            heartbeat_interval_seconds=0.1,
            heartbeat_timeout_seconds=0.3,
        ),
    )
    assert result.status is RunStatus.SUCCEEDED
    assert result.live_summary is not None
    assert result.live_summary.telemetry_status is TelemetryStatus.INCOMPLETE
    with postgres_factory() as session:
        live = session.get(LiveTelemetrySessionRecord, result.run_id)
        assert live is not None
        assert live.connection_count == connection_count
        assert live.gap_count == gap_count
        assert live.negotiated_subscriptions == {
            "connection_epoch": connection_count,
            "subscriptions": [
                {"update_type": "date", "frequency": "daily"},
                {"update_type": "company_info", "frequency": "automatic"},
                {"update_type": "company_economy", "frequency": "monthly"},
                {"update_type": "company_stats", "frequency": "monthly"},
            ],
        }
        assert live.telemetry_status == "incomplete"
        rows = session.scalars(
            select(TelemetryObservationRecord)
            .where(TelemetryObservationRecord.experiment_run_id == result.run_id)
            .order_by(TelemetryObservationRecord.sequence)
        ).all()
        assert [row.sequence for row in rows] == list(range(1, len(rows) + 1))
        assert {row.connection_epoch for row in rows if row.kind == ObservationKind.DATE} == set(
            range(1, connection_count + 1)
        )
        assert (
            sum(
                row.kind == ObservationKind.DIAGNOSTIC
                and row.payload["code"] == DiagnosticCode.CONNECTION_GAP
                for row in rows
            )
            == gap_count
        )


@pytest.mark.parametrize("mode", ["bad_auth", "bad_protocol"])
def test_postgres_pre_ready_failure_has_no_negotiated_subscriptions(
    postgres_factory: sessionmaker[Session], tmp_path: Path, mode: str
) -> None:
    from sqlalchemy import text

    from app.simulation.openttd.live_launch import LiveLaunchPreparation
    from app.simulation.openttd.live_runner import LiveSimulationRunner

    engine = postgres_factory.kw["bind"]
    Base.metadata.create_all(engine)
    with postgres_factory() as session:
        schema = session.scalar(text("SELECT current_schema()"))
    url = engine.url.update_query_dict({"options": f"-c search_path={schema}"})
    runtime = _runtime(tmp_path, mode)

    def live_factory(config, options, root, processor_factory):
        return LiveSimulationRunner(
            _Assets(runtime, config),
            LiveLaunchPreparation(
                tmp_path / "runs", lock_root=tmp_path / "locks", port_range=(41000, 41200)
            ),
            expected_identity=_identity(),
            final_result=_fixture_result,
            options=options,
            telemetry_factory=processor_factory,
        )

    result = ExperimentService(
        postgres_factory,
        FakeRunner(),
        live_runner_factory=live_factory,
        telemetry_store_factory=lambda: TelemetryRepository(url),
    ).run(_config(), artifact_dir=tmp_path, execution_mode=ExecutionMode.LIVE)
    assert result.status is RunStatus.FAILED
    with postgres_factory() as session:
        live = session.get(LiveTelemetrySessionRecord, result.run_id)
        assert live is not None and live.negotiated_subscriptions is None


def test_postgres_reconnect_exhaustion_keeps_gap_and_typed_failure(
    postgres_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    from sqlalchemy import text

    from app.simulation.openttd.live_launch import LiveLaunchPreparation
    from app.simulation.openttd.live_runner import LiveSimulationRunner

    engine = postgres_factory.kw["bind"]
    Base.metadata.create_all(engine)
    with postgres_factory() as session:
        schema = session.scalar(text("SELECT current_schema()"))
    url = engine.url.update_query_dict({"options": f"-c search_path={schema}"})
    runtime = _runtime(tmp_path, "reconnect_exhausted")

    def live_factory(config, options, root, processor_factory):
        return LiveSimulationRunner(
            _Assets(runtime, config),
            LiveLaunchPreparation(
                tmp_path / "runs", lock_root=tmp_path / "locks", port_range=(41000, 41200)
            ),
            expected_identity=_identity(),
            final_result=_fixture_result,
            options=options,
            telemetry_factory=processor_factory,
        )

    result = ExperimentService(
        postgres_factory,
        FakeRunner(),
        live_runner_factory=live_factory,
        telemetry_store_factory=lambda: TelemetryRepository(url),
    ).run(
        _config(),
        artifact_dir=tmp_path,
        execution_mode=ExecutionMode.LIVE,
        live_options=_options(
            running_timeout_seconds=4,
            reconnect_budget_seconds=0.4,
            heartbeat_interval_seconds=0.1,
            heartbeat_timeout_seconds=0.3,
        ),
    )
    assert result.status is RunStatus.FAILED
    assert result.failure_code is ExecutionFailureCode.OBSERVER_LOST
    with postgres_factory() as session:
        run = session.get(ExperimentRunRecord, result.run_id)
        live = session.get(LiveTelemetrySessionRecord, result.run_id)
        assert run is not None and run.failure_code == ExecutionFailureCode.OBSERVER_LOST
        assert run.simulation is None
        assert live is not None
        assert live.connection_count == 1
        assert live.gap_count == 1
        assert live.telemetry_status == "failed"
        assert live.negotiated_subscriptions is not None
        assert live.negotiated_subscriptions["connection_epoch"] == 1
        assert session.scalar(select(ExperimentMetricRecord.id)) is None


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


def test_postgres_terminal_failure_keeps_telemetry_and_publishes_success_evidence(
    postgres_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    from sqlalchemy import text

    from app.experiments.repository import ExperimentRepository

    engine = postgres_factory.kw["bind"]
    Base.metadata.create_all(engine)
    with postgres_factory() as session:
        schema = session.scalar(text("SELECT current_schema()"))
    url = engine.url.update_query_dict({"options": f"-c search_path={schema}"})
    calls = 0

    class BrokenRepository(ExperimentRepository):
        def complete_run(self, session, run_id, result, completed_at):
            super().complete_run(session, run_id, result, completed_at)
            raise RuntimeError("controlled terminal database failure")

    class LiveRunner:
        def __init__(self, processor_factory):
            self.processor_factory = processor_factory

        def run(self, config, *, run_id, artifact_dir):
            nonlocal calls
            calls += 1

            async def observe() -> None:
                processor = self.processor_factory(run_id)
                processor.start()
                processor.emit(ObserverHealth(ObserverState.CONNECTING))
                processor.emit(ObserverHealth(ObserverState.CONNECTED))
                processor.emit(ObserverHealth(ObserverState.AUTHENTICATED))
                processor.emit(ObserverMeasurement(GameDateObservation(game_day=712223)))
                await processor.close()

            asyncio.run(observe())
            reference, summary = _controlled_artifacts(artifact_dir, run_id)
            return SimulationResult(
                simulation_date=date(1950, 1, 2),
                savegame_version=302,
                metrics=(Metric(name="company_money", value=42, unit="GBP"),),
                raw_artifact_reference=reference,
                live_summary=summary,
            )

    result = ExperimentService(
        postgres_factory,
        FakeRunner(),
        BrokenRepository(),
        live_runner_factory=lambda config, options, root, factory: LiveRunner(factory),
        telemetry_store_factory=lambda: TelemetryRepository(url),
    ).run(baseline_config(), artifact_dir=tmp_path, execution_mode=ExecutionMode.LIVE)
    assert calls == 1
    assert result.failure_code is ExecutionFailureCode.PERSISTENCE_FAILURE
    manifest = json.loads((tmp_path / f"run-{result.run_id}/outcome-v1.json").read_text())
    assert manifest["run_id"] == result.run_id
    assert manifest["intended_status"] == "succeeded"
    assert manifest["simulation"]["metrics"][0]["value"] == 42
    with postgres_factory() as session:
        row = session.get(ExperimentRunRecord, result.run_id)
        live = session.get(LiveTelemetrySessionRecord, result.run_id)
        assert row is not None and row.status == RunStatus.RUNNING
        assert row.simulation is None
        assert live is not None and live.persisted_count == 2
        assert session.scalar(select(ExperimentMetricRecord.id)) is None
        assert len(session.scalars(select(TelemetryObservationRecord)).all()) == 2
