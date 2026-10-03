"""T16 cross-run acceptance using controlled peers and isolated PostgreSQL."""

import asyncio
import hashlib
import json
import os
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pytest
from postgres_support import postgres_factory as postgres_factory
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker
from test_experiments import FakeRunner, baseline_config
from test_live_runner import _Assets, _config, _fixture_result, _identity, _options, _runtime

from app.database.base import Base
from app.experiments import cli
from app.experiments.domain import (
    ExecutionFailureCode,
    ExecutionMode,
    LiveExecutionSummary,
    Metric,
    RunStatus,
    SimulationExecutionError,
    SimulationResult,
    TelemetryStatus,
)
from app.experiments.model import (
    ExperimentRunRecord,
    LiveTelemetrySessionRecord,
    TelemetryObservationRecord,
)
from app.experiments.outcome_recovery import OutcomeRecoveryService, RecoveryStatus
from app.experiments.repository import ExperimentRepository
from app.experiments.service import ExperimentService
from app.experiments.telemetry_repository import TelemetryRepository
from app.simulation.openttd.admin_observer import (
    AdminObserver,
    ObserverHealth,
    ObserverMeasurement,
    ObserverState,
)
from app.simulation.openttd.live_launch import LiveLaunchPreparation
from app.simulation.openttd.live_runner import LiveSimulationRunner
from app.simulation.openttd.telemetry import GameDateObservation, ObservationKind


@pytest.mark.skipif(os.name != "posix", reason="controlled process-group isolation requires POSIX")
@pytest.mark.parametrize(
    ("failure_mode", "expected"),
    [
        ("cancel", ExecutionFailureCode.CANCELLED),
        ("cross_run_password", ExecutionFailureCode.AUTHENTICATION_FAILURE),
    ],
)
def test_two_controlled_peers_keep_ports_processes_and_cancellation_separate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure_mode: str,
    expected: ExecutionFailureCode,
) -> None:
    """The shared allocator and owner cleanup operate on independent children."""
    spawn_barrier = threading.Barrier(3)
    cancellation_a = threading.Event()
    spawned: list[int] = []
    prepared = []
    secret_snapshots: list[tuple[str, str, str, str, str]] = []
    original_spawn = asyncio.create_subprocess_exec

    def cross_run_password(host, port, password, *args, **kwargs):
        other_password = next(
            item.admin_password for item in prepared if item.admin_password != password
        )
        return AdminObserver(host, port, other_password, *args, **kwargs)

    async def capture_spawn(*args, **kwargs):
        child = await original_spawn(*args, **kwargs)
        spawned.append(child.pid)
        await asyncio.to_thread(spawn_barrier.wait, 5)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", capture_spawn)
    runners = []
    for label, mode, cancellation in (
        ("a", "no_target", cancellation_a),
        ("b", "normal", threading.Event()),
    ):
        runtime_root = tmp_path / label
        runtime_root.mkdir()
        runtime = _runtime(runtime_root, mode)
        launch = LiveLaunchPreparation(
            tmp_path / "workspaces", lock_root=tmp_path / "locks", port_range=(41000, 41200)
        )

        class CaptureLaunch:
            def __init__(self, preparation: LiveLaunchPreparation) -> None:
                self.preparation = preparation

            def prepare(self, config, prepared_runtime, *, deadline=None):
                owned = self.preparation.prepare(config, prepared_runtime, deadline=deadline)
                prepared.append(owned)
                assert stat.S_IMODE(owned.workspace.stat().st_mode) == 0o700
                assert stat.S_IMODE(owned.secrets_config_path.stat().st_mode) == 0o600
                secret_snapshots.append(
                    (
                        owned.admin_password,
                        repr(owned.argv),
                        repr(owned.provenance),
                        owned.main_config_path.read_text(),
                        owned.private_config_path.read_text(),
                    )
                )
                return owned

        runners.append(
            LiveSimulationRunner(
                _Assets(runtime),
                CaptureLaunch(launch),
                expected_identity=_identity(),
                final_result=_fixture_result,
                options=_options(running_timeout_seconds=5),
                cancellation=cancellation,
                observer_factory=(
                    cross_run_password
                    if label == "a" and failure_mode == "cross_run_password"
                    else AdminObserver
                ),
            )
        )

    def execute(index: int):
        try:
            return runners[index].run(
                _config(), run_id=index + 1, artifact_dir=tmp_path / f"artifacts-{index + 1}"
            )
        except SimulationExecutionError as exc:
            return exc.failure

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(execute, 0)
        second = executor.submit(execute, 1)
        try:
            spawn_barrier.wait(5)
            if failure_mode == "cancel":
                cancellation_a.set()
            outcome_a = first.result(timeout=10)
            outcome_b = second.result(timeout=10)
        finally:
            cancellation_a.set()

    assert outcome_a.code is expected
    assert isinstance(outcome_b, SimulationResult)
    assert len(spawned) == len(set(spawned)) == 2
    assert len(prepared) == 2
    assert len({item.game_port for item in prepared}) == 2
    assert len({item.admin_port for item in prepared}) == 2
    assert len({port for item in prepared for port in (item.game_port, item.admin_port)}) == 4
    assert len({item.workspace for item in prepared}) == 2
    assert len({item.admin_password for item in prepared}) == 2
    visible = repr((outcome_a, outcome_b)) + repr(capsys.readouterr())
    for password, argv, provenance, main_config, private_config in secret_snapshots:
        assert password not in visible + argv + provenance + main_config + private_config
    assert all(item.private_config_path.name == "private.cfg" for item in prepared)
    assert all(item.lease.closed and not item.workspace.exists() for item in prepared)
    for pid in spawned:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


def test_postgres_parallel_runs_keep_telemetry_terminal_failure_and_recovery_isolated(
    postgres_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    """A failed terminal transaction for A cannot roll back or rewrite B."""
    engine = postgres_factory.kw["bind"]
    Base.metadata.create_all(engine)
    with postgres_factory() as session:
        schema = session.scalar(text("SELECT current_schema()"))
    url = engine.url.update_query_dict({"options": f"-c search_path={schema}"})
    barrier = threading.Barrier(2)
    executions: list[int] = []

    class OneRunRepository(ExperimentRepository):
        def complete_run(self, session, run_id, result, completed_at):
            super().complete_run(session, run_id, result, completed_at)
            if result.metrics[0].value == 11:
                raise RuntimeError("controlled terminal DB rollback")

    class ControlledRunner:
        def __init__(self, processor_factory, metric_value: int):
            self.processor_factory = processor_factory
            self.metric_value = metric_value

        def run(self, config, *, run_id, artifact_dir):
            executions.append(run_id)

            async def observe():
                processor = self.processor_factory(run_id)
                processor.start()
                processor.emit(ObserverHealth(ObserverState.CONNECTING))
                processor.emit(ObserverHealth(ObserverState.CONNECTED))
                processor.emit(ObserverHealth(ObserverState.AUTHENTICATED))
                processor.emit(
                    ObserverMeasurement(GameDateObservation(game_day=712220 + self.metric_value))
                )
                await processor.close()

            asyncio.run(observe())
            raw = f"raw-{run_id}".encode()
            parsed = f"parsed-{run_id}".encode()
            (artifact_dir / "final.sav").write_bytes(raw)
            (artifact_dir / "parsed.json.gz").write_bytes(parsed)
            barrier.wait(5)
            return SimulationResult(
                simulation_date=date(1950, 1, 2),
                savegame_version=302,
                metrics=(Metric(name="company_money", value=self.metric_value, unit="GBP"),),
                raw_artifact_reference=f"run-{run_id}/parsed.json.gz",
                live_summary=LiveExecutionSummary(
                    telemetry_status=TelemetryStatus.INCOMPLETE,
                    received_count=2,
                    persisted_count=2,
                    last_sequence=2,
                    raw_save_reference=f"run-{run_id}/final.sav",
                    raw_save_sha256=hashlib.sha256(raw).hexdigest(),
                    parsed_artifact_reference=f"run-{run_id}/parsed.json.gz",
                    parsed_artifact_sha256=hashlib.sha256(parsed).hexdigest(),
                ),
            )

    def run(value: int):
        return ExperimentService(
            postgres_factory,
            FakeRunner(),
            OneRunRepository(),
            live_runner_factory=lambda config, options, root, factory: ControlledRunner(
                factory, value
            ),
            telemetry_store_factory=lambda: TelemetryRepository(url),
        ).run(baseline_config(), artifact_dir=tmp_path, execution_mode=ExecutionMode.LIVE)

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_a = executor.submit(run, 11)
        future_b = executor.submit(run, 22)
        result_a = future_a.result(timeout=15)
        result_b = future_b.result(timeout=15)

    assert result_a.run_id != result_b.run_id
    assert result_a.failure_code is ExecutionFailureCode.PERSISTENCE_FAILURE
    assert result_b.status is RunStatus.SUCCEEDED
    assert len(executions) == len(set(executions)) == 2
    path_a = tmp_path / f"run-{result_a.run_id}" / "outcome-v1.json"
    path_b = tmp_path / f"run-{result_b.run_id}" / "outcome-v1.json"
    assert path_a.exists() and path_b.exists()
    assert json.loads(path_a.read_text())["run_id"] == result_a.run_id
    assert json.loads(path_b.read_text())["run_id"] == result_b.run_id

    with postgres_factory() as session:
        row_a = session.get(ExperimentRunRecord, result_a.run_id)
        row_b = session.get(ExperimentRunRecord, result_b.run_id)
        assert row_a is not None and row_a.status == RunStatus.RUNNING and row_a.simulation is None
        assert row_b is not None and row_b.status == RunStatus.SUCCEEDED
        assert row_b.simulation is not None and row_b.simulation.metrics[0].value == 22
        assert session.get(LiveTelemetrySessionRecord, result_a.run_id) is not None
        assert session.get(LiveTelemetrySessionRecord, result_b.run_id) is not None
        observations = session.scalars(
            select(TelemetryObservationRecord).order_by(
                TelemetryObservationRecord.experiment_run_id,
                TelemetryObservationRecord.sequence,
            )
        ).all()
        assert len(observations) == 4
        assert {item.experiment_run_id for item in observations} == {
            result_a.run_id,
            result_b.run_id,
        }
        for run_id, value in ((result_a.run_id, 11), (result_b.run_id, 22)):
            own = [item for item in observations if item.experiment_run_id == run_id]
            assert [item.sequence for item in own] == [1, 2]
            assert own[-1].game_day == 712220 + value

    recovery = OutcomeRecoveryService(postgres_factory)
    assert recovery.recover(tmp_path, path_a).status is RecoveryStatus.RECOVERED
    assert recovery.recover(tmp_path, path_a).status is RecoveryStatus.ALREADY_RECONCILED
    assert recovery.recover(tmp_path, path_b).status is RecoveryStatus.ALREADY_RECONCILED
    wrong_path = tmp_path / f"run-{result_b.run_id}" / f"../run-{result_a.run_id}/outcome-v1.json"
    assert recovery.recover(tmp_path, wrong_path).status is RecoveryStatus.INVALID_MANIFEST
    with postgres_factory() as session:
        row_b = session.get(ExperimentRunRecord, result_b.run_id)
        assert row_b is not None and row_b.simulation is not None
        assert row_b.simulation.metrics[0].value == 22
        assert len(session.scalars(select(TelemetryObservationRecord)).all()) == 4

    with postgres_factory.begin() as session:
        row_a = session.get(ExperimentRunRecord, result_a.run_id)
        assert row_a is not None and row_a.simulation is not None
        row_a.simulation.metrics[0].value = 999
    assert recovery.recover(tmp_path, path_a).status is RecoveryStatus.CONFLICT
    with postgres_factory() as session:
        row_a = session.get(ExperimentRunRecord, result_a.run_id)
        row_b = session.get(ExperimentRunRecord, result_b.run_id)
        assert row_a is not None and row_a.simulation.metrics[0].value == 999
        assert row_b is not None and row_b.simulation.metrics[0].value == 22


def test_postgres_controlled_live_secret_stays_out_of_every_durable_and_cli_surface(
    postgres_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Scan the actual service result, DB, artifact, and CLI rendering together."""
    engine = postgres_factory.kw["bind"]
    Base.metadata.create_all(engine)
    with postgres_factory() as session:
        schema = session.scalar(text("SELECT current_schema()"))
    url = engine.url.update_query_dict({"options": f"-c search_path={schema}"})
    runtime = _runtime(tmp_path, "normal")
    launch = LiveLaunchPreparation(
        tmp_path / "workspaces", lock_root=tmp_path / "locks", port_range=(41000, 41200)
    )
    passwords: list[str] = []
    run_ids: list[int] = []

    class CaptureLaunch:
        def prepare(self, config, prepared_runtime, *, deadline=None):
            owned = launch.prepare(config, prepared_runtime, deadline=deadline)
            passwords.append(owned.admin_password)
            assert stat.S_IMODE(owned.workspace.stat().st_mode) == 0o700
            assert stat.S_IMODE(owned.secrets_config_path.stat().st_mode) == 0o600
            return owned

    async def final_result(prepared, progress, config):
        run_id = run_ids[0]
        artifact_dir = tmp_path / f"run-{run_id}"
        raw = prepared.final_save_path.read_bytes()
        parsed = b"controlled parsed evidence"
        (artifact_dir / "final.sav").write_bytes(raw)
        (artifact_dir / "parsed.json.gz").write_bytes(parsed)
        reference = f"run-{run_id}/parsed.json.gz"
        return SimulationResult(
            simulation_date=date(1950, 1, 31),
            savegame_version=302,
            metrics=(Metric(name="company_money", value=7, unit="GBP"),),
            raw_artifact_reference=reference,
            live_summary=LiveExecutionSummary(
                telemetry_status=TelemetryStatus.INCOMPLETE,
                raw_save_reference=f"run-{run_id}/final.sav",
                raw_save_sha256=hashlib.sha256(raw).hexdigest(),
                parsed_artifact_reference=reference,
                parsed_artifact_sha256=hashlib.sha256(parsed).hexdigest(),
            ),
        )

    class CapturedRunner(LiveSimulationRunner):
        def run(self, config, *, run_id, artifact_dir):
            run_ids.append(run_id)
            return super().run(config, run_id=run_id, artifact_dir=artifact_dir)

    def live_factory(config, options, root, processor_factory):
        return CapturedRunner(
            _Assets(runtime, config),
            CaptureLaunch(),
            expected_identity=_identity(),
            final_result=final_result,
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
        live_options=_options(running_timeout_seconds=4),
    )
    assert result.status is RunStatus.SUCCEEDED
    assert len(passwords) == 1
    assert run_ids == [result.run_id]
    assert result.live_summary is not None
    assert result.live_summary.telemetry_status is TelemetryStatus.INCOMPLETE
    with postgres_factory() as session:
        row = session.get(ExperimentRunRecord, result.run_id)
        live = session.get(LiveTelemetrySessionRecord, result.run_id)
        observations = session.scalars(
            select(TelemetryObservationRecord).where(
                TelemetryObservationRecord.experiment_run_id == result.run_id
            )
        ).all()
        assert row is not None and row.execution_metadata is not None
        assert live is not None and live.telemetry_status == TelemetryStatus.INCOMPLETE
        assert ObservationKind.DATE in {item.kind for item in observations}
        assert ObservationKind.COMPANY_INFO not in {item.kind for item in observations}
        durable = json.dumps(row.execution_metadata) + json.dumps(
            [item.payload for item in observations]
        )
    manifest = tmp_path / f"run-{result.run_id}" / "outcome-v1.json"
    durable += manifest.read_text() + result.model_dump_json()
    artifact_bytes = b"".join(
        path.read_bytes() for path in manifest.parent.iterdir() if path.is_file()
    )

    class ReturnedService:
        def run(self, config, *, artifact_dir, execution_mode):
            return result

    monkeypatch.setattr(cli, "ExperimentService", lambda **kwargs: ReturnedService())
    assert cli.main(["run", "--mode", "live", "--artifact-dir", str(tmp_path)]) == 3
    output = capsys.readouterr()
    for password in passwords:
        assert password not in durable + output.out + output.err
        assert password.encode() not in artifact_bytes
