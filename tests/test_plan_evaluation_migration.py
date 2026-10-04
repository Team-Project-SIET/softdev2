"""P07 forward migration and data-preserving downgrade policy."""

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from postgres_support import (
    current_metadata_diff,
    upgrade_isolated,
)
from postgres_support import (
    postgres_factory as postgres_factory,
)
from sqlalchemy import create_engine, inspect, text


@pytest.mark.parametrize("initial", [None, "0007"])
def test_fresh_and_current_upgrade(initial):
    scripts = ScriptDirectory(str(Path(__file__).parents[1] / "alembic"))
    engine = create_engine("sqlite://")
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        for rev in ("0001", "0002", "0003", "0004", "0006", "0007"):
            scripts.get_revision(rev).module.upgrade()
        scripts.get_revision("0008").module.upgrade()
        assert "plan_evaluations" in inspect(connection).get_table_names()
        assert current_metadata_diff(connection) == []
        scripts.get_revision("0008").module.downgrade()
        assert "plan_evaluations" not in inspect(connection).get_table_names()
    engine.dispose()


@pytest.mark.parametrize("initial", ["base", "0007"])
def test_postgres_fresh_and_upgrade(postgres_factory, initial):
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    engine = postgres_factory.kw["bind"]
    if initial != "base":
        upgrade_isolated(config, engine, initial)
    upgrade_isolated(config, engine, "head")
    with engine.connect() as connection:
        assert current_metadata_diff(connection) == []
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0008"


def test_downgrade_refuses_plan_history(session_factory, tmp_path):
    from app.experiments.service import ExperimentService
    from tests.test_plan_evaluation import ControlledPlanRunner, plan_world, request

    value = plan_world(request(), tmp_path / "world.sav")
    ExperimentService(session_factory).run_plan(
        value,
        world_source=tmp_path / "world.sav",
        artifact_dir=tmp_path / "runs",
        runner_factory=ControlledPlanRunner,
    )
    scripts = ScriptDirectory(str(Path(__file__).parents[1] / "alembic"))
    with (
        session_factory.kw["bind"].begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
    ):
        with pytest.raises(RuntimeError, match="archival"):
            scripts.get_revision("0008").module.downgrade()
        assert "plan_evaluations" in inspect(connection).get_table_names()


def test_postgres_plan_provenance_and_terminal_recovery(postgres_factory, tmp_path):
    from app.database.base import Base
    from tests.test_plan_evaluation import (
        test_successful_plan_run_and_reload,
        test_terminal_persistence_failure_recovery_preserves_plan,
    )

    Base.metadata.create_all(postgres_factory.kw["bind"])
    test_successful_plan_run_and_reload(postgres_factory, tmp_path)
    other = tmp_path / "recovery"
    other.mkdir()
    test_terminal_persistence_failure_recovery_preserves_plan(postgres_factory, other)
