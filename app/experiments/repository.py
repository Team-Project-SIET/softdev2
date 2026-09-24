"""SQLAlchemy persistence for experiment history."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.experiments.domain import ExperimentConfig, RunStatus, SimulationResult
from app.experiments.model import (
    ExperimentMetricRecord,
    ExperimentRunRecord,
    ExperimentScenario,
    PlanningStrategyRecord,
    SimulationRunRecord,
)


class ExperimentRepository:
    def create_run(self, session: Session, config: ExperimentConfig, started_at) -> int:
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

    def fail_run(self, session: Session, run_id: int, error: str, completed_at) -> None:
        run = session.get(ExperimentRunRecord, run_id)
        if run is None or run.status != RunStatus.RUNNING:
            raise ValueError(f"experiment run {run_id} is not running")
        run.error = error
        run.completed_at = completed_at
        run.status = RunStatus.FAILED
