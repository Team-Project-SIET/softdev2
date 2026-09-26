"""Select batch or live execution and commit one experiment outcome."""

from __future__ import annotations

import configparser
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from sqlalchemy.orm import Session

from app.database.session import create_session
from app.experiments.domain import (
    ExecutionFailureCode,
    ExecutionMode,
    ExperimentConfig,
    ExperimentResult,
    LiveExecutionOptions,
    RunStatus,
    SimulationExecutionError,
    TelemetryStatus,
)
from app.experiments.repository import ExperimentRepository
from app.simulation.openttd.runner import OpenTTDLabRunner, SimulationRunner

if TYPE_CHECKING:
    from app.simulation.openttd.telemetry_processor import AsyncTelemetryStore, TelemetryProcessor


def _default_telemetry_store() -> AsyncTelemetryStore:
    from app.experiments.telemetry_repository import TelemetryRepository

    return TelemetryRepository()


class LiveRunnerFactory(Protocol):
    def __call__(
        self,
        config: ExperimentConfig,
        options: LiveExecutionOptions,
        artifact_root: Path,
        telemetry_factory: Callable[[int], TelemetryProcessor],
    ) -> SimulationRunner: ...


def _default_live_runner(
    config: ExperimentConfig,
    options: LiveExecutionOptions,
    artifact_root: Path,
    telemetry_factory: Callable[[int], TelemetryProcessor],
) -> SimulationRunner:
    """Construct live dependencies only after its run/session creation commits."""
    from app.simulation.openttd.admin_observer import ExpectedServerIdentity
    from app.simulation.openttd.live_launch import LiveLaunchPreparation
    from app.simulation.openttd.live_runner import LiveSimulationRunner
    from app.simulation.openttd.runtime_assets import PinnedRuntimePreparer

    scenario = configparser.ConfigParser(interpolation=None)
    scenario.read_string(config.scenario.openttd_config)
    width = 1 << scenario.getint("game_creation", "map_x", fallback=8)
    height = 1 << scenario.getint("game_creation", "map_y", fallback=8)
    return LiveSimulationRunner(
        PinnedRuntimePreparer(artifact_root / ".live-runtime-cache"),
        LiveLaunchPreparation(artifact_root / ".live-workspaces"),
        expected_identity=ExpectedServerIdentity(
            config.openttd_version, config.seed, "", width, height, 0
        ),
        options=options,
        telemetry_factory=telemetry_factory,
    )


class ExperimentService:
    def __init__(
        self,
        session_factory: Callable[[], Session] = create_session,
        runner: SimulationRunner | None = None,
        repository: ExperimentRepository | None = None,
        *,
        live_runner_factory: LiveRunnerFactory = _default_live_runner,
        telemetry_store_factory: Callable[[], AsyncTelemetryStore] = _default_telemetry_store,
    ) -> None:
        self.session_factory = session_factory
        self.runner = runner or OpenTTDLabRunner()  # Existing batch injection remains valid.
        self.repository = repository or ExperimentRepository()
        self.live_runner_factory = live_runner_factory
        self.telemetry_store_factory = telemetry_store_factory

    def run(
        self,
        config: ExperimentConfig,
        *,
        artifact_dir: Path,
        execution_mode: ExecutionMode = ExecutionMode.BATCH,
        live_options: LiveExecutionOptions | None = None,
    ) -> ExperimentResult:
        mode = ExecutionMode(execution_mode)
        if mode is ExecutionMode.BATCH and live_options is not None:
            raise ValueError("live options require live execution mode")
        if mode is ExecutionMode.LIVE:
            from app.simulation.openttd.telemetry_processor import TelemetryProcessor

            options = (live_options or LiveExecutionOptions()).resolved_for_duration(
                config.duration_days
            )
            if (
                options.persistence_queue_capacity != TelemetryProcessor.CAPACITY
                or options.persistence_batch_size != TelemetryProcessor.BATCH_SIZE
                or options.persistence_flush_interval_seconds != TelemetryProcessor.FLUSH_SECONDS
            ):
                raise ValueError("unsupported live telemetry buffering options")
            metadata = {"resolved_options": options.model_dump(mode="json")}
        else:
            options = None
            metadata = None

        started_at = datetime.now(UTC)
        with self.session_factory() as session, session.begin():
            run_id = self.repository.create_run(
                session,
                config,
                started_at,
                execution_mode=mode,
                execution_metadata=metadata,
            )
            if mode is ExecutionMode.LIVE:
                self.repository.create_live_session(session, run_id, started_at)
        if mode is ExecutionMode.BATCH:
            return self._run_batch(config, run_id, started_at, artifact_dir)
        assert options is not None
        return self._run_live(config, run_id, started_at, artifact_dir, options)

    def _run_batch(
        self, config: ExperimentConfig, run_id: int, started_at: datetime, artifact_dir: Path
    ) -> ExperimentResult:
        try:
            simulation = self.runner.run(config, run_id=run_id, artifact_dir=artifact_dir)
            completed_at = datetime.now(UTC)
            with self.session_factory() as session, session.begin():
                self.repository.complete_run(session, run_id, simulation, completed_at)
        except Exception as exc:
            completed_at = datetime.now(UTC)
            with self.session_factory() as session, session.begin():
                self.repository.fail_run(session, run_id, str(exc), completed_at)
            return ExperimentResult(
                run_id=run_id,
                config=config,
                status=RunStatus.FAILED,
                started_at=started_at,
                completed_at=completed_at,
                error=str(exc),
            )
        return ExperimentResult(
            run_id=run_id,
            config=config,
            status=RunStatus.SUCCEEDED,
            started_at=started_at,
            completed_at=completed_at,
            simulation=simulation,
        )

    def _run_live(
        self,
        config: ExperimentConfig,
        run_id: int,
        started_at: datetime,
        artifact_root: Path,
        options: LiveExecutionOptions,
    ) -> ExperimentResult:
        run_artifacts = artifact_root / f"run-{run_id}"

        def processor_factory(processor_run_id: int) -> TelemetryProcessor:
            from app.simulation.openttd.telemetry_processor import TelemetryProcessor

            if processor_run_id != run_id:
                raise ValueError("telemetry run linkage mismatch")
            return TelemetryProcessor(
                processor_run_id,
                self.telemetry_store_factory(),
                retry_budget=options.persistence_retry_budget_seconds,
                flush_timeout=options.final_flush_timeout_seconds,
            )

        try:
            run_artifacts.mkdir(parents=True, exist_ok=False)
            runner = self.live_runner_factory(config, options, artifact_root, processor_factory)
            simulation = runner.run(config, run_id=run_id, artifact_dir=run_artifacts)
        except SimulationExecutionError as exc:
            completed_at = datetime.now(UTC)
            failure = exc.failure
            with self.session_factory() as session, session.begin():
                summary = self.repository.finish_live_session(
                    session,
                    run_id,
                    completed_at,
                    summary=failure.live_summary,
                    failure_code=failure.code,
                    error=failure.message,
                )
                self.repository.fail_run(
                    session,
                    run_id,
                    failure.message,
                    completed_at,
                    failure_code=failure.code,
                    partial_artifact_reference=failure.partial_artifact_reference,
                )
            return ExperimentResult(
                run_id=run_id,
                config=config,
                status=RunStatus.FAILED,
                started_at=started_at,
                completed_at=completed_at,
                error=failure.message,
                execution_mode=ExecutionMode.LIVE,
                failure_code=failure.code,
                live_summary=summary,
            )
        except Exception:
            completed_at = datetime.now(UTC)
            message = "live integration failure"
            with self.session_factory() as session, session.begin():
                summary = self.repository.finish_live_session(
                    session, run_id, completed_at, summary=None, error=message
                )
                self.repository.fail_run(session, run_id, message, completed_at)
            return ExperimentResult(
                run_id=run_id,
                config=config,
                status=RunStatus.FAILED,
                started_at=started_at,
                completed_at=completed_at,
                error=message,
                execution_mode=ExecutionMode.LIVE,
                live_summary=summary,
            )

        completed_at = datetime.now(UTC)
        with self.session_factory() as session, session.begin():
            summary = self.repository.finish_live_session(
                session, run_id, completed_at, summary=simulation.live_summary
            )
            if summary.telemetry_status is TelemetryStatus.FAILED:
                self.repository.fail_run(
                    session,
                    run_id,
                    "persistence failure",
                    completed_at,
                    failure_code=ExecutionFailureCode.PERSISTENCE_FAILURE,
                    partial_artifact_reference=summary.raw_save_reference,
                )
            else:
                simulation = simulation.model_copy(update={"live_summary": summary})
                self.repository.complete_run(session, run_id, simulation, completed_at)
        if summary.telemetry_status is TelemetryStatus.FAILED:
            return ExperimentResult(
                run_id=run_id,
                config=config,
                status=RunStatus.FAILED,
                started_at=started_at,
                completed_at=completed_at,
                error="persistence failure",
                execution_mode=ExecutionMode.LIVE,
                failure_code=ExecutionFailureCode.PERSISTENCE_FAILURE,
                live_summary=summary,
            )
        return ExperimentResult(
            run_id=run_id,
            config=config,
            status=RunStatus.SUCCEEDED,
            started_at=started_at,
            completed_at=completed_at,
            simulation=simulation,
            execution_mode=ExecutionMode.LIVE,
            live_summary=summary,
        )
