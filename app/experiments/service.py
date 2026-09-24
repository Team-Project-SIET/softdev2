"""Record every simulation attempt and its typed result."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.database.session import create_session
from app.experiments.domain import ExperimentConfig, ExperimentResult, RunStatus
from app.experiments.repository import ExperimentRepository
from app.simulation.openttd.runner import OpenTTDLabRunner, SimulationRunner


class ExperimentService:
    def __init__(
        self,
        session_factory: Callable[[], Session] = create_session,
        runner: SimulationRunner | None = None,
        repository: ExperimentRepository | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.runner = runner or OpenTTDLabRunner()
        self.repository = repository or ExperimentRepository()

    def run(self, config: ExperimentConfig, *, artifact_dir: Path) -> ExperimentResult:
        started_at = datetime.now(UTC)
        with self.session_factory() as session, session.begin():
            run_id = self.repository.create_run(session, config, started_at)
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
