"""SQLAlchemy persistence for experiment history."""

from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.experiments.domain import (
    ExecutionFailureCode,
    ExecutionMode,
    ExperimentConfig,
    LiveExecutionOptions,
    RunStatus,
    SimulationResult,
)
from app.experiments.model import (
    ExperimentMetricRecord,
    ExperimentRunRecord,
    ExperimentScenario,
    PlanningStrategyRecord,
    SimulationRunRecord,
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
        elif key == "artifact_reference":
            if (
                not isinstance(value, str)
                or not value
                or any(
                    marker in value.lower()
                    for marker in ("password=", "secret=", "credential=", "token=")
                )
            ):
                raise ValueError("sensitive execution metadata is not permitted")
        else:
            raise ValueError("sensitive execution metadata is not permitted")


class ExperimentRepository:
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
    ) -> None:
        run = session.get(ExperimentRunRecord, run_id)
        if run is None or run.status != RunStatus.RUNNING:
            raise ValueError(f"experiment run {run_id} is not running")
        run.error = error
        run.failure_code = failure_code
        run.completed_at = completed_at
        run.status = RunStatus.FAILED
