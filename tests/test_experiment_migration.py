from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from postgres_support import current_metadata_diff
from sqlalchemy import create_engine, inspect


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
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                for revision in ("0001", "0002", "0003", "0004"):
                    scripts.get_revision(revision).module.upgrade()
                before = set(inspect(connection).get_table_names())
                migration.upgrade()
                assert set(inspect(connection).get_table_names()) == before | new_names
                telemetry_migration.upgrade()
                assert (
                    set(inspect(connection).get_table_names())
                    == before | new_names | telemetry_names
                )
                assert current_metadata_diff(connection) == []
                telemetry_migration.downgrade()
                assert set(inspect(connection).get_table_names()) == before | new_names
                migration.downgrade()
            assert set(inspect(connection).get_table_names()) == before
    finally:
        engine.dispose()
