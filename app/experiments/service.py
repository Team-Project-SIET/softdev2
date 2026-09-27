"""Select batch or live execution and commit one experiment outcome."""

from __future__ import annotations

import configparser
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from sqlalchemy.orm import Session

from app.database.session import create_session
from app.experiments.cancellation import LiveCancellation
from app.experiments.domain import (
    ExecutionFailure,
    ExecutionFailureCode,
    ExecutionMode,
    ExperimentConfig,
    ExperimentResult,
    LiveExecutionOptions,
    LiveExecutionSummary,
    RunStatus,
    SimulationExecutionError,
    SimulationResult,
    TelemetryStatus,
)
from app.experiments.model import ExperimentRunRecord
from app.experiments.outcome_manifest import OutcomeManifest, new_manifest, publish_manifest
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


def _matches_terminal(
    row: ExperimentRunRecord | None,
    config: ExperimentConfig,
    simulation: SimulationResult | None,
    code: ExecutionFailureCode | None,
    message: str | None,
    summary: LiveExecutionSummary | None,
    partial_reference: str | None,
) -> bool:
    """Confirm an ambiguous commit only if the stored outcome is this outcome."""
    if row is None or row.execution_mode != ExecutionMode.LIVE:
        return False
    if (
        row.scenario.identifier != config.scenario.identifier
        or row.scenario.version != config.scenario.version
        or row.scenario.openttd_config != config.scenario.openttd_config
        or row.strategy.identifier != config.planning.strategy_identifier
        or row.strategy.version != config.planning.strategy_version
        or row.strategy_configuration != config.planning.parameters
        or row.ai_configuration != config.ai.model_dump(mode="json")
        or row.openttd_version != config.openttd_version
        or row.opengfx_version != config.opengfx_version
        or row.seed != config.seed
        or row.duration_days != config.duration_days
    ):
        return False
    live = row.telemetry_session
    if (
        live is None
        or summary is None
        or (
            live.telemetry_status != summary.telemetry_status
            or live.received_count != summary.received_count
            or live.persisted_count != summary.persisted_count
            or live.gap_count != summary.gap_count
            or live.dropped_count != summary.dropped_count
            or live.last_observed_sequence != summary.last_sequence
            or live.process_exit_code != summary.process_exit_code
        )
    ):
        return False
    if simulation is not None:
        stored = row.simulation
        return (
            row.status == RunStatus.SUCCEEDED
            and row.failure_code is None
            and stored is not None
            and stored.simulation_date == simulation.simulation_date
            and stored.savegame_version == simulation.savegame_version
            and row.raw_artifact_reference == simulation.raw_artifact_reference
            and sorted((item.name, item.value, item.unit) for item in stored.metrics)
            == sorted(
                (item.name, Decimal(str(item.value)), item.unit) for item in simulation.metrics
            )
        )
    return (
        row.status == RunStatus.FAILED
        and row.failure_code == code
        and row.error == message
        and row.simulation is None
        and row.raw_artifact_reference == partial_reference
    )


def _default_live_runner(
    config: ExperimentConfig,
    options: LiveExecutionOptions,
    artifact_root: Path,
    telemetry_factory: Callable[[int], TelemetryProcessor],
    *,
    cancellation: LiveCancellation | None = None,
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
        cancellation=cancellation.event if cancellation is not None else None,
    )


class ExperimentService:
    def __init__(
        self,
        session_factory: Callable[[], Session] = create_session,
        runner: SimulationRunner | None = None,
        repository: ExperimentRepository | None = None,
        *,
        live_runner_factory: LiveRunnerFactory | None = None,
        telemetry_store_factory: Callable[[], AsyncTelemetryStore] = _default_telemetry_store,
        live_cancellation: LiveCancellation | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.runner = runner or OpenTTDLabRunner()  # Existing batch injection remains valid.
        self.repository = repository or ExperimentRepository()
        self.live_runner_factory = live_runner_factory or partial(
            _default_live_runner, cancellation=live_cancellation
        )
        self.telemetry_store_factory = telemetry_store_factory
        self.live_cancellation = live_cancellation

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
            if self.live_cancellation is not None and self.live_cancellation.event.is_set():
                raise SimulationExecutionError(
                    ExecutionFailure(
                        code=ExecutionFailureCode.CANCELLED,
                        message="cancelled",
                        live_summary=simulation.live_summary,
                    )
                )
        except SimulationExecutionError as exc:
            return self._record_live_outcome(
                config, run_id, started_at, run_artifacts, failure=exc.failure
            )
        except Exception:
            return self._record_live_outcome(
                config, run_id, started_at, run_artifacts, integration_failure=True
            )

        return self._record_live_outcome(
            config, run_id, started_at, run_artifacts, simulation=simulation
        )

    def _record_live_outcome(
        self,
        config: ExperimentConfig,
        run_id: int,
        started_at: datetime,
        run_artifacts: Path,
        *,
        simulation: SimulationResult | None = None,
        failure: ExecutionFailure | None = None,
        integration_failure: bool = False,
    ) -> ExperimentResult:
        """Publish intended evidence before the terminal DB commit can fail."""
        completed_at = datetime.now(UTC)
        message = (
            failure.code.value.replace("_", " ")
            if failure is not None
            else "live integration failure"
            if integration_failure
            else None
        )
        summary = (
            failure.live_summary
            if failure is not None
            else (simulation.live_summary if simulation is not None else None)
        )
        code = failure.code if failure is not None else None
        if (
            code is None
            and summary is not None
            and summary.telemetry_status is TelemetryStatus.FAILED
        ):
            code = ExecutionFailureCode.PERSISTENCE_FAILURE
            message = "persistence failure"
        manifest_path: str | None = None
        manifest_failed = False
        manifest: OutcomeManifest | None = None
        terminal_simulation: SimulationResult | None = None

        def build_manifest() -> OutcomeManifest:
            intended_simulation = terminal_simulation or (
                simulation if code is None and not integration_failure else None
            )
            partial_reference = (
                failure.partial_artifact_reference
                if failure is not None
                else summary.raw_save_reference
                if code is not None and summary is not None
                else None
            )
            return new_manifest(
                config,
                run_id,
                simulation=intended_simulation,
                failure_code=code,
                failure_message=message,
                partial_artifact_reference=partial_reference,
                live_summary=summary,
            )

        try:
            with self.session_factory() as session, session.begin():
                summary = self.repository.finish_live_session(
                    session,
                    run_id,
                    completed_at,
                    summary=summary,
                    failure_code=code,
                    error=message,
                )
                if (
                    code is None
                    and not integration_failure
                    and summary.telemetry_status is TelemetryStatus.FAILED
                ):
                    code = ExecutionFailureCode.PERSISTENCE_FAILURE
                    message = "persistence failure"
                terminal_simulation = (
                    simulation.model_copy(update={"live_summary": summary})
                    if simulation is not None and code is None and not integration_failure
                    else None
                )
                try:
                    manifest = build_manifest()
                    manifest_path = publish_manifest(run_artifacts.parent, manifest)
                except Exception:
                    manifest_failed = True
                if terminal_simulation is not None:
                    self.repository.complete_run(session, run_id, terminal_simulation, completed_at)
                else:
                    self.repository.fail_run(
                        session,
                        run_id,
                        message or "live integration failure",
                        completed_at,
                        failure_code=code,
                        partial_artifact_reference=(
                            failure.partial_artifact_reference
                            if failure is not None
                            else summary.raw_save_reference
                            if code is not None
                            else None
                        ),
                        termination_signal=(
                            self.live_cancellation.signal_name
                            if code is ExecutionFailureCode.CANCELLED
                            and self.live_cancellation is not None
                            else None
                        ),
                    )
        except Exception:
            if manifest_path is None and not manifest_failed and run_artifacts.is_dir():
                try:
                    if manifest is None:
                        manifest = build_manifest()
                    manifest_path = publish_manifest(run_artifacts.parent, manifest)
                except Exception:
                    manifest_failed = True
            # A driver exception does not prove whether the server committed.
            # The failed Session is closed; inspect the run only through a fresh one.
            committed = False
            try:
                with self.session_factory() as verification:
                    row = verification.get(ExperimentRunRecord, run_id)
                    committed = _matches_terminal(
                        row,
                        config,
                        terminal_simulation,
                        code,
                        message,
                        summary,
                        (
                            failure.partial_artifact_reference
                            if failure is not None
                            else summary.raw_save_reference
                            if code is not None and summary is not None
                            else None
                        ),
                    )
            except Exception:
                pass
            if not committed:
                return ExperimentResult(
                    run_id=run_id,
                    config=config,
                    status=RunStatus.FAILED,
                    started_at=started_at,
                    completed_at=completed_at,
                    error=(
                        f"{message}; outcome persistence unconfirmed; manifest unavailable"
                        if manifest_failed and message is not None
                        else "outcome persistence unconfirmed; manifest unavailable"
                        if manifest_failed
                        else f"{message}; outcome persistence unconfirmed"
                        if message is not None
                        else "outcome persistence unconfirmed"
                    ),
                    execution_mode=ExecutionMode.LIVE,
                    failure_code=code or ExecutionFailureCode.PERSISTENCE_FAILURE,
                    terminal_persistence_failed=True,
                    outcome_manifest_failed=manifest_failed,
                    live_summary=(
                        summary.model_copy(update={"outcome_manifest_reference": manifest_path})
                        if summary is not None
                        else None
                    ),
                )
        if summary is not None and manifest_path is not None:
            summary = summary.model_copy(update={"outcome_manifest_reference": manifest_path})
        return ExperimentResult(
            run_id=run_id,
            config=config,
            status=RunStatus.SUCCEEDED if terminal_simulation is not None else RunStatus.FAILED,
            started_at=started_at,
            completed_at=completed_at,
            simulation=(
                terminal_simulation.model_copy(update={"live_summary": summary})
                if terminal_simulation is not None
                else None
            ),
            error=(
                f"{message}; outcome manifest unavailable"
                if manifest_failed and message is not None
                else "outcome manifest unavailable"
                if manifest_failed
                else message
            ),
            execution_mode=ExecutionMode.LIVE,
            failure_code=code,
            live_summary=summary,
            outcome_manifest_failed=manifest_failed,
        )
