from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from app.database import models as _models  # noqa: F401
from app.database.base import Base


def test_experiment_migration_is_additive_and_reversible() -> None:
    scripts = ScriptDirectory(str(Path(__file__).resolve().parents[1] / "alembic"))
    migration = scripts.get_revision("0006").module
    telemetry_migration = scripts.get_revision("0007").module
    new_names = {
        "experiment_scenarios",
        "planning_strategies",
        "experiment_runs",
        "simulation_runs",
        "experiment_metrics",
    }
    telemetry_names = {"live_telemetry_sessions", "telemetry_observations"}
    old_tables = [
        table
        for table in Base.metadata.sorted_tables
        if table.name not in new_names | telemetry_names
    ]
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            Base.metadata.create_all(connection, tables=old_tables)
            before = set(inspect(connection).get_table_names())
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                migration.upgrade()
                assert set(inspect(connection).get_table_names()) == before | new_names
                telemetry_migration.upgrade()
                assert (
                    set(inspect(connection).get_table_names())
                    == before | new_names | telemetry_names
                )
                assert compare_metadata(context, Base.metadata) == []
                telemetry_migration.downgrade()
                assert set(inspect(connection).get_table_names()) == before | new_names
                migration.downgrade()
            assert set(inspect(connection).get_table_names()) == before
    finally:
        engine.dispose()
