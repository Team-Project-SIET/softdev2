"""SQLAlchemy persistence for experiment history."""

import re
from datetime import datetime
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.experiments.domain import (
    ExecutionFailureCode,
    ExecutionMode,
    ExperimentConfig,
    LiveExecutionOptions,
    LiveExecutionSummary,
    RunStatus,
    SimulationResult,
    TelemetryStatus,
)
from app.experiments.model import (
    ExperimentMetricRecord,
    ExperimentRunRecord,
    ExperimentScenario,
    LiveTelemetrySessionRecord,
    PlanningStrategyRecord,
    SimulationRunRecord,
    TelemetryObservationRecord,
)


def _require_sanitized_metadata(metadata: dict) -> None:
    """Accept only T02 provenance fields with a defined nonsecret shape.

    Later tickets can extend this boundary when asset manifest types exist.
    """
    for key, value in metadata.items():
        if key in {"initial_day", "target_day", "actual_day"}:
            if type(value) is not int or value < 0:
                raise ValueError("sensitive execution metadata is not permitted")
        elif key == "resolved_options":
            if not isinstance(value, dict):
                raise ValueError("sensitive execution metadata is not permitted")
            try:
                LiveExecutionOptions.model_validate(value)
            except ValidationError as exc:
                raise ValueError("sensitive execution metadata is not permitted") from exc
        elif key in {
            "artifact_reference",
            "raw_save_reference",
            "parsed_artifact_reference",
        }:
            if (
                not isinstance(value, str)
                or not value
                or "://" in value
                or any(ord(character) < 32 for character in value)
                or any(
                    marker in value.lower()
                    for marker in ("password=", "secret=", "credential=", "token=")
                )
            ):
                raise ValueError("sensitive execution metadata is not permitted")
        elif key in {"raw_save_sha256", "parsed_artifact_sha256"}:
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValueError("sensitive execution metadata is not permitted")
        else:
            raise ValueError("sensitive execution metadata is not permitted")


class ExperimentRepository:
    def create_live_session(self, session: Session, run_id: int, started_at: datetime) -> None:
        session.add(
            LiveTelemetrySessionRecord(
                experiment_run_id=run_id,
                telemetry_status=TelemetryStatus.PENDING,
                started_at=started_at,
            )
        )

    def finish_live_session(
        self,
        session: Session,
        run_id: int,
        completed_at: datetime,
        *,
        summary: LiveExecutionSummary | None,
        failure_code: ExecutionFailureCode | None = None,
        error: str | None = None,
    ) -> LiveExecutionSummary:
        from app.simulation.openttd.telemetry import ObservationKind

        row = session.get(LiveTelemetrySessionRecord, run_id)
        run = session.get(ExperimentRunRecord, run_id)
        if row is None or run is None or run.execution_mode != ExecutionMode.LIVE:
            raise ValueError("live telemetry session missing")
        summary = summary or LiveExecutionSummary(telemetry_status=TelemetryStatus.INCOMPLETE)
        kinds = set(
            session.scalars(
                select(TelemetryObservationRecord.kind)
                .where(TelemetryObservationRecord.experiment_run_id == run_id)
                .distinct()
            ).all()
        )
        required = {
            ObservationKind.DATE,
            ObservationKind.COMPANY_INFO,
            ObservationKind.COMPANY_ECONOMY,
            ObservationKind.COMPANY_STATS,
        }
        telemetry_failed = (
            row.telemetry_status == TelemetryStatus.FAILED
            or summary.telemetry_status is TelemetryStatus.FAILED
        )
        complete = (
            failure_code is None
            and error is None
            and not telemetry_failed
            and required <= kinds
            and row.connection_count > 0
            and row.received_count == row.persisted_count
            and row.received_count > 0
            and row.gap_count == row.dropped_count == 0
            and row.last_observed_sequence == row.final_persisted_sequence
        )
        status = (
            TelemetryStatus.FAILED
            if failure_code is not None or error is not None or telemetry_failed
            else TelemetryStatus.COMPLETE
            if complete
            else TelemetryStatus.INCOMPLETE
        )
        row.telemetry_status = status
        row.ended_at = completed_at
        row.terminal_reason = (
            failure_code.value
            if failure_code is not None
            else ExecutionFailureCode.PERSISTENCE_FAILURE.value
            if telemetry_failed
            else None
        )
        row.error_summary = error[:1024] if error is not None else row.error_summary
        row.process_exit_code = summary.process_exit_code
        if summary.last_observed_day is not None:
            row.last_observed_day = summary.last_observed_day
        metadata = dict(run.execution_metadata or {})
        if summary.requested_target_day is not None:
            metadata["target_day"] = summary.requested_target_day
        if summary.actual_final_day is not None:
            metadata["actual_day"] = summary.actual_final_day
        for name in (
            "raw_save_reference",
            "raw_save_sha256",
            "parsed_artifact_reference",
            "parsed_artifact_sha256",
        ):
            value = getattr(summary, name)
            if value is not None:
                metadata[name] = value
        _require_sanitized_metadata(metadata)
        run.execution_metadata = metadata
        return summary.model_copy(
            update={
                "telemetry_status": status,
                "received_count": row.received_count,
                "persisted_count": row.persisted_count,
                "gap_count": row.gap_count,
                "dropped_count": row.dropped_count,
                "last_sequence": row.last_observed_sequence,
                "last_observed_day": (
                    summary.last_observed_day
                    if summary.last_observed_day is not None
                    else row.last_observed_day
                ),
            }
        )

    def create_run(
        self,
        session: Session,
        config: ExperimentConfig,
        started_at,
        *,
        execution_mode: ExecutionMode = ExecutionMode.BATCH,
        execution_metadata: dict | None = None,
    ) -> int:
        if execution_metadata is not None:
            _require_sanitized_metadata(execution_metadata)
        scenario = session.scalar(
            select(ExperimentScenario).where(
                ExperimentScenario.identifier == config.scenario.identifier,
                ExperimentScenario.version == config.scenario.version,
            )
        )
        if scenario is None:
            scenario = ExperimentScenario(**config.scenario.model_dump())
            session.add(scenario)
        elif scenario.openttd_config != config.scenario.openttd_config:
            raise ValueError("scenario version already exists with different OpenTTD configuration")
        strategy = session.scalar(
            select(PlanningStrategyRecord).where(
                PlanningStrategyRecord.identifier == config.planning.strategy_identifier,
                PlanningStrategyRecord.version == config.planning.strategy_version,
            )
        )
        if strategy is None:
            strategy = PlanningStrategyRecord(
                identifier=config.planning.strategy_identifier,
                version=config.planning.strategy_version,
            )
            session.add(strategy)
        run = ExperimentRunRecord(
            scenario=scenario,
            strategy=strategy,
            strategy_configuration=config.planning.parameters,
            ai_configuration=config.ai.model_dump(mode="json"),
            openttd_version=config.openttd_version,
            opengfx_version=config.opengfx_version,
            seed=config.seed,
            duration_days=config.duration_days,
            started_at=started_at,
            status=RunStatus.RUNNING,
            execution_mode=execution_mode,
            execution_metadata=execution_metadata,
        )
        session.add(run)
        session.flush()
        return run.id

    def complete_run(
        self, session: Session, run_id: int, result: SimulationResult, completed_at
    ) -> None:
        run = session.get(ExperimentRunRecord, run_id)
        if run is None or run.status != RunStatus.RUNNING:
            raise ValueError(f"experiment run {run_id} is not running")
        run.simulation = SimulationRunRecord(
            simulation_date=result.simulation_date,
            savegame_version=result.savegame_version,
            metrics=[
                ExperimentMetricRecord(
                    name=metric.name,
                    value=Decimal(str(metric.value)),
                    unit=metric.unit,
                )
                for metric in result.metrics
            ],
        )
        run.raw_artifact_reference = result.raw_artifact_reference
        run.completed_at = completed_at
        run.status = RunStatus.SUCCEEDED

    def fail_run(
        self,
        session: Session,
        run_id: int,
        error: str,
        completed_at,
        *,
        failure_code: ExecutionFailureCode | None = None,
        partial_artifact_reference: str | None = None,
    ) -> None:
        run = session.get(ExperimentRunRecord, run_id)
        if run is None or run.status != RunStatus.RUNNING:
            raise ValueError(f"experiment run {run_id} is not running")
        run.error = error
        run.failure_code = failure_code
        if partial_artifact_reference is not None:
            _require_sanitized_metadata({"artifact_reference": partial_artifact_reference})
            run.raw_artifact_reference = partial_artifact_reference
        run.completed_at = completed_at
        run.status = RunStatus.FAILED
