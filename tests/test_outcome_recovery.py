"""T15 explicit reconciliation uses retained evidence, never a runner."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from postgres_support import postgres_factory as postgres_factory
from sqlalchemy import event, select
from sqlalchemy.orm import Session, sessionmaker
from test_experiments import baseline_config

from app.database.base import Base
from app.experiments.domain import (
    ExecutionFailureCode,
    ExecutionMode,
    LiveExecutionSummary,
    Metric,
    RunStatus,
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
from app.experiments.outcome_manifest import new_manifest, publish_manifest
from app.experiments.outcome_recovery import OutcomeRecoveryService, RecoveryStatus
from app.experiments.repository import ExperimentRepository


def _initial_run(factory: sessionmaker[Session]) -> int:
    repository = ExperimentRepository()
    with factory.begin() as session:
        run_id = repository.create_run(
            session, baseline_config(), datetime.now(UTC), execution_mode=ExecutionMode.LIVE
        )
        repository.create_live_session(session, run_id, datetime.now(UTC))
    return run_id


def _success_manifest(root: Path, run_id: int, *, observation_count: int = 0) -> Path:
    directory = root / f"run-{run_id}"
    directory.mkdir()
    (directory / "final.sav").write_bytes(b"controlled raw save")
    (directory / "parsed.json.gz").write_bytes(b"controlled parsed artifact")
    reference = f"run-{run_id}/parsed.json.gz"
    summary = LiveExecutionSummary(
        telemetry_status=TelemetryStatus.INCOMPLETE,
        raw_save_reference=f"run-{run_id}/final.sav",
        parsed_artifact_reference=reference,
        received_count=observation_count,
        persisted_count=observation_count,
        last_sequence=observation_count or None,
    )
    simulation = SimulationResult(
        simulation_date=date(1950, 1, 2),
        savegame_version=302,
        metrics=(Metric(name="company_money", value=42, unit="GBP"),),
        raw_artifact_reference=reference,
    )
    publish_manifest(
        root,
        new_manifest(baseline_config(), run_id, simulation=simulation, live_summary=summary),
    )
    return directory / "outcome-v1.json"


def _failure_manifest(
    root: Path, run_id: int, code: ExecutionFailureCode, *, observation_count: int = 0
) -> Path:
    directory = root / f"run-{run_id}"
    directory.mkdir()
    (directory / "partial.sav").write_bytes(b"controlled partial")
    publish_manifest(
        root,
        new_manifest(
            baseline_config(),
            run_id,
            failure_code=code,
            failure_message=code.value.replace("_", " "),
            partial_artifact_reference=f"run-{run_id}/partial.sav",
            live_summary=LiveExecutionSummary(
                telemetry_status=TelemetryStatus.FAILED,
                received_count=observation_count,
                persisted_count=observation_count,
                last_sequence=observation_count or None,
            ),
        ),
    )
    return directory / "outcome-v1.json"


def test_success_recovery_is_idempotent_and_does_not_fabricate_telemetry(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    run_id = _initial_run(session_factory)
    manifest_path = _success_manifest(tmp_path, run_id)
    recovery = OutcomeRecoveryService(session_factory)
    assert recovery.recover(tmp_path, manifest_path).status is RecoveryStatus.RECOVERED
    assert recovery.recover(tmp_path, manifest_path).status is RecoveryStatus.ALREADY_RECONCILED
    with session_factory() as session:
        row = session.get(ExperimentRunRecord, run_id)
        assert row is not None and row.status == RunStatus.SUCCEEDED
        assert row.simulation is not None and row.simulation.savegame_version == 302
        assert row.raw_artifact_reference == f"run-{run_id}/parsed.json.gz"
        assert session.scalars(select(ExperimentMetricRecord)).all()[0].value == 42
        assert len(session.scalars(select(SimulationRunRecord)).all()) == 1
        assert len(session.scalars(select(TelemetryObservationRecord)).all()) == 0
        live = session.get(LiveTelemetrySessionRecord, run_id)
        assert live is not None and live.telemetry_status == TelemetryStatus.INCOMPLETE
    assert manifest_path.exists()


@pytest.mark.parametrize(
    "code",
    [
        ExecutionFailureCode.TIMEOUT,
        ExecutionFailureCode.CANCELLED,
        ExecutionFailureCode.OBSERVER_LOST,
        ExecutionFailureCode.PERSISTENCE_FAILURE,
        ExecutionFailureCode.UNEXPECTED_SHUTDOWN,
    ],
)
def test_failure_recovery_preserves_code_and_partial_artifact(
    session_factory: sessionmaker[Session], tmp_path: Path, code: ExecutionFailureCode
) -> None:
    run_id = _initial_run(session_factory)
    path = _failure_manifest(tmp_path, run_id, code)
    recovery = OutcomeRecoveryService(session_factory)
    assert recovery.recover(tmp_path, path).status is RecoveryStatus.RECOVERED
    assert recovery.recover(tmp_path, path).status is RecoveryStatus.ALREADY_RECONCILED
    with session_factory() as session:
        row = session.get(ExperimentRunRecord, run_id)
        assert row is not None and row.status == RunStatus.FAILED
        assert row.failure_code == code
        assert row.raw_artifact_reference == f"run-{run_id}/partial.sav"
        assert row.simulation is None
        assert session.scalar(select(ExperimentMetricRecord.id)) is None
        live = session.get(LiveTelemetrySessionRecord, run_id)
        assert live is not None and live.telemetry_status == TelemetryStatus.FAILED


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ("version", RecoveryStatus.UNSUPPORTED_VERSION),
        ("run_id", RecoveryStatus.INVALID_MANIFEST),
        ("extra", RecoveryStatus.INVALID_MANIFEST),
        ("traversal", RecoveryStatus.INVALID_MANIFEST),
        ("digest", RecoveryStatus.INVALID_MANIFEST),
        ("unsafe_metric_name", RecoveryStatus.INVALID_MANIFEST),
    ],
)
def test_invalid_manifest_never_changes_run(
    session_factory: sessionmaker[Session], tmp_path: Path, change: str, expected: RecoveryStatus
) -> None:
    run_id = _initial_run(session_factory)
    path = _success_manifest(tmp_path, run_id)
    document = json.loads(path.read_text())
    if change == "version":
        document["schema_version"] = 2
    elif change == "run_id":
        document["run_id"] = run_id + 1
    elif change == "extra":
        document["environment"] = {"SECRET": "private"}
    elif change == "traversal":
        document["simulation"]["raw_artifact_reference"] = "../other/parsed.json.gz"
    elif change == "digest":
        document["final_artifact_sha256"] = "0" * 64
    elif change == "unsafe_metric_name":
        document["simulation"]["metrics"][0]["name"] = "password=secret"
    path.write_text(json.dumps(document))
    assert OutcomeRecoveryService(session_factory).recover(tmp_path, path).status is expected
    with session_factory() as session:
        row = session.get(ExperimentRunRecord, run_id)
        assert row is not None and row.status == RunStatus.RUNNING
        assert row.simulation is None


def test_conflicting_terminal_row_is_not_overwritten(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    run_id = _initial_run(session_factory)
    path = _success_manifest(tmp_path, run_id)
    with session_factory.begin() as session:
        ExperimentRepository().fail_run(
            session, run_id, "timeout", datetime.now(UTC), failure_code=ExecutionFailureCode.TIMEOUT
        )
    assert (
        OutcomeRecoveryService(session_factory).recover(tmp_path, path).status
        is RecoveryStatus.CONFLICT
    )
    with session_factory() as session:
        row = session.get(ExperimentRunRecord, run_id)
        assert row is not None and row.failure_code == ExecutionFailureCode.TIMEOUT
        assert row.simulation is None


def test_wrong_configuration_and_missing_run_are_conflicts(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    run_id = _initial_run(session_factory)
    path = _success_manifest(tmp_path, run_id)
    with session_factory.begin() as session:
        row = session.get(ExperimentRunRecord, run_id)
        assert row is not None
        row.seed += 1
    recovery = OutcomeRecoveryService(session_factory)
    assert recovery.recover(tmp_path, path).status is RecoveryStatus.CONFLICT
    with session_factory.begin() as session:
        row = session.get(ExperimentRunRecord, run_id)
        assert row is not None
        session.delete(row)
    assert recovery.recover(tmp_path, path).status is RecoveryStatus.CONFLICT


@pytest.mark.parametrize(
    "damage", ["missing_raw", "missing_parsed", "symlink", "nested_extra", "malformed"]
)
def test_untrusted_success_manifest_is_rejected_before_db_mutation(
    session_factory: sessionmaker[Session], tmp_path: Path, damage: str
) -> None:
    run_id = _initial_run(session_factory)
    path = _success_manifest(tmp_path, run_id)
    directory = path.parent
    if damage == "missing_raw":
        (directory / "final.sav").unlink()
    elif damage == "missing_parsed":
        (directory / "parsed.json.gz").unlink()
    elif damage == "symlink":
        (directory / "final.sav").unlink()
        (directory / "final.sav").symlink_to(tmp_path / "outside.sav")
    elif damage == "nested_extra":
        document = json.loads(path.read_text())
        document["simulation"]["driver_exception"] = "secret"
        path.write_text(json.dumps(document))
    else:
        path.write_bytes(b"{malformed")
    assert (
        OutcomeRecoveryService(session_factory).recover(tmp_path, path).status
        is RecoveryStatus.INVALID_MANIFEST
    )
    with session_factory() as session:
        row = session.get(ExperimentRunRecord, run_id)
        assert row is not None and row.status == RunStatus.RUNNING


def test_recovery_db_failure_rolls_back_without_leaking_driver_text(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    run_id = _initial_run(session_factory)
    path = _success_manifest(tmp_path, run_id)

    class BrokenRepository(ExperimentRepository):
        def complete_run(self, session, run_id, result, completed_at):
            super().complete_run(session, run_id, result, completed_at)
            raise RuntimeError("secret driver detail")

    result = OutcomeRecoveryService(session_factory, BrokenRepository()).recover(tmp_path, path)
    assert result.status is RecoveryStatus.FAILED
    assert "secret" not in result.model_dump_json()
    with session_factory() as session:
        row = session.get(ExperimentRunRecord, run_id)
        assert row is not None and row.status == RunStatus.RUNNING
        assert row.simulation is None


def test_lost_commit_acknowledgement_uses_fresh_session(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    run_id = _initial_run(session_factory)
    path = _success_manifest(tmp_path, run_id)

    class AmbiguousSession(Session):
        pass

    @event.listens_for(AmbiguousSession, "after_commit")
    def lose_acknowledgement(session: AmbiguousSession) -> None:
        if session.info.pop("lose_ack", False):
            raise RuntimeError("secret commit acknowledgement")

    factory = sessionmaker(
        bind=session_factory.kw["bind"], class_=AmbiguousSession, expire_on_commit=False
    )

    class AmbiguousRepository(ExperimentRepository):
        def complete_run(self, session, run_id, result, completed_at):
            super().complete_run(session, run_id, result, completed_at)
            session.info["lose_ack"] = True

    result = OutcomeRecoveryService(factory, AmbiguousRepository()).recover(tmp_path, path)
    assert result.status is RecoveryStatus.RECOVERED
    assert "secret" not in result.model_dump_json()
    assert (
        OutcomeRecoveryService(factory).recover(tmp_path, path).status
        is RecoveryStatus.ALREADY_RECONCILED
    )


def test_changed_metric_conflicts_with_existing_success(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    run_id = _initial_run(session_factory)
    path = _success_manifest(tmp_path, run_id)
    with session_factory.begin() as session:
        repository = ExperimentRepository()
        summary = LiveExecutionSummary(telemetry_status=TelemetryStatus.INCOMPLETE)
        repository.finish_live_session(session, run_id, datetime.now(UTC), summary=summary)
        repository.complete_run(
            session,
            run_id,
            SimulationResult(
                simulation_date=date(1950, 1, 2),
                savegame_version=302,
                metrics=(Metric(name="company_money", value=999, unit="GBP"),),
                raw_artifact_reference=f"run-{run_id}/parsed.json.gz",
            ),
            datetime.now(UTC),
        )
    assert (
        OutcomeRecoveryService(session_factory).recover(tmp_path, path).status
        is RecoveryStatus.CONFLICT
    )


@pytest.mark.parametrize(
    ("stored_status", "stored_reason"),
    [
        (TelemetryStatus.FAILED, ExecutionFailureCode.OBSERVER_LOST.value),
        (TelemetryStatus.COMPLETE, None),
        (TelemetryStatus.RECORDING, ExecutionFailureCode.OBSERVER_LOST.value),
    ],
)
def test_conflicting_telemetry_terminal_evidence_is_never_overwritten(
    session_factory: sessionmaker[Session],
    tmp_path: Path,
    stored_status: TelemetryStatus,
    stored_reason: str | None,
) -> None:
    run_id = _initial_run(session_factory)
    path = _success_manifest(tmp_path, run_id)
    with session_factory.begin() as session:
        live = session.get(LiveTelemetrySessionRecord, run_id)
        assert live is not None
        live.telemetry_status = stored_status
        live.terminal_reason = stored_reason
    assert (
        OutcomeRecoveryService(session_factory).recover(tmp_path, path).status
        is RecoveryStatus.CONFLICT
    )
    with session_factory() as session:
        row = session.get(ExperimentRunRecord, run_id)
        live = session.get(LiveTelemetrySessionRecord, run_id)
        assert row is not None and row.status == RunStatus.RUNNING
        assert live is not None and live.telemetry_status == stored_status
        assert live.terminal_reason == stored_reason


def test_missing_stored_artifact_hash_is_not_an_exact_match(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    run_id = _initial_run(session_factory)
    path = _success_manifest(tmp_path, run_id)
    with session_factory.begin() as session:
        repository = ExperimentRepository()
        summary = LiveExecutionSummary(
            telemetry_status=TelemetryStatus.INCOMPLETE,
            raw_save_reference=f"run-{run_id}/final.sav",
            parsed_artifact_reference=f"run-{run_id}/parsed.json.gz",
        )
        repository.finish_live_session(session, run_id, datetime.now(UTC), summary=summary)
        repository.complete_run(
            session,
            run_id,
            SimulationResult(
                simulation_date=date(1950, 1, 2),
                savegame_version=302,
                metrics=(Metric(name="company_money", value=42, unit="GBP"),),
                raw_artifact_reference=f"run-{run_id}/parsed.json.gz",
            ),
            datetime.now(UTC),
        )
    assert (
        OutcomeRecoveryService(session_factory).recover(tmp_path, path).status
        is RecoveryStatus.CONFLICT
    )
    with session_factory() as session:
        row = session.get(ExperimentRunRecord, run_id)
        assert row is not None and row.status == RunStatus.SUCCEEDED
        assert row.execution_metadata is not None
        assert "raw_save_sha256" not in row.execution_metadata


@pytest.mark.parametrize("field", ["metric_value", "failure_code"])
def test_v1_trusts_plausible_local_outcome_fields_when_db_is_running(
    session_factory: sessionmaker[Session], tmp_path: Path, field: str
) -> None:
    run_id = _initial_run(session_factory)
    path = (
        _success_manifest(tmp_path, run_id)
        if field == "metric_value"
        else _failure_manifest(tmp_path, run_id, ExecutionFailureCode.TIMEOUT)
    )
    document = json.loads(path.read_text())
    if field == "metric_value":
        document["simulation"]["metrics"][0]["value"] = 99.0
    else:
        document["failure_code"] = ExecutionFailureCode.CANCELLED.value
        document["failure_message"] = "cancelled"
    path.write_text(json.dumps(document))
    assert (
        OutcomeRecoveryService(session_factory).recover(tmp_path, path).status
        is RecoveryStatus.RECOVERED
    )
    with session_factory() as session:
        row = session.get(ExperimentRunRecord, run_id)
        assert row is not None
        if field == "metric_value":
            assert row.simulation is not None and row.simulation.metrics[0].value == 99
        else:
            assert row.failure_code == ExecutionFailureCode.CANCELLED


@pytest.mark.parametrize("outcome", ["success", "failure"])
def test_postgres_recovery_is_idempotent_and_keeps_telemetry(
    postgres_factory: sessionmaker[Session], tmp_path: Path, outcome: str
) -> None:
    Base.metadata.create_all(postgres_factory.kw["bind"])
    run_id = _initial_run(postgres_factory)
    with postgres_factory.begin() as session:
        live = session.get(LiveTelemetrySessionRecord, run_id)
        assert live is not None
        live.received_count = 1
        live.persisted_count = 1
        live.last_observed_sequence = 1
        live.final_persisted_sequence = 1
        session.add(
            TelemetryObservationRecord(
                experiment_run_id=run_id,
                sequence=1,
                connection_epoch=0,
                received_at=datetime.now(UTC),
                source="live_runtime",
                schema_version=1,
                kind="diagnostic",
                date_quality="unknown",
                payload={"event": "controlled"},
            )
        )
    path = (
        _success_manifest(tmp_path, run_id, observation_count=1)
        if outcome == "success"
        else _failure_manifest(tmp_path, run_id, ExecutionFailureCode.TIMEOUT, observation_count=1)
    )
    recovery = OutcomeRecoveryService(postgres_factory)
    assert recovery.recover(tmp_path, path).status is RecoveryStatus.RECOVERED
    assert recovery.recover(tmp_path, path).status is RecoveryStatus.ALREADY_RECONCILED
    with postgres_factory() as session:
        row = session.get(ExperimentRunRecord, run_id)
        assert row is not None and row.status == (
            RunStatus.SUCCEEDED if outcome == "success" else RunStatus.FAILED
        )
        expected = 1 if outcome == "success" else 0
        assert len(session.scalars(select(SimulationRunRecord)).all()) == expected
        assert len(session.scalars(select(ExperimentMetricRecord)).all()) == expected
        observations = session.scalars(select(TelemetryObservationRecord)).all()
        assert len(observations) == 1 and observations[0].sequence == 1
        live = session.get(LiveTelemetrySessionRecord, run_id)
        assert live is not None and live.persisted_count == 1


def test_postgres_concurrent_recovery_creates_one_result(
    postgres_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    Base.metadata.create_all(postgres_factory.kw["bind"])
    run_id = _initial_run(postgres_factory)
    path = _success_manifest(tmp_path, run_id)
    recovery = OutcomeRecoveryService(postgres_factory)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: recovery.recover(tmp_path, path).status, range(2)))
    assert set(results) == {RecoveryStatus.RECOVERED, RecoveryStatus.ALREADY_RECONCILED}
    with postgres_factory() as session:
        assert len(session.scalars(select(SimulationRunRecord)).all()) == 1
        assert len(session.scalars(select(ExperimentMetricRecord)).all()) == 1
