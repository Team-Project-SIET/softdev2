"""The research ORM must work without the retired operational application."""

import subprocess
import sys
from io import StringIO
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from postgres_support import current_metadata_diff
from sqlalchemy import create_engine, text

from app.database.base import Base


def test_current_registry_and_sessions_work_without_legacy_packages() -> None:
    script = """
import importlib.abc
import sys

class RejectLegacy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[:2] in [
            ['app', name] for name in
            ('customer', 'driver', 'shipment', 'vehicle', 'routing', 'packing', 'tui')
        ] or fullname.startswith('app.integrations.line'):
            raise AssertionError('retired application import: ' + fullname)

sys.meta_path.insert(0, RejectLegacy())
sys.path.insert(0, 'tests')
from postgres_support import postgres_factory, upgrade_isolated
from alembic.script import ScriptDirectory
scripts = ScriptDirectory('alembic')
assert scripts.get_heads() == ['0007']
assert [r.revision for r in scripts.walk_revisions()] == [
    '0007', '0006', '0005', '0004', '0003', '0002', '0001',
]
from app.database import models
from app.database.base import Base
from app.database.session import create_session
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, configure_mappers

assert set(Base.metadata.tables) == {
    'experiment_scenarios', 'planning_strategies', 'experiment_runs',
    'simulation_runs', 'experiment_metrics', 'live_telemetry_sessions',
    'telemetry_observations',
}
configure_mappers()
engine = create_engine('sqlite+pysqlite:///:memory:')
Base.metadata.create_all(engine)
assert set(inspect(engine).get_table_names()) == set(Base.metadata.tables)
import app.database.session as sessions
sessions.get_engine = lambda: engine
with create_session() as session:
    assert isinstance(session, Session)
    assert session.get_bind() is engine
Base.metadata.drop_all(engine)
engine.dispose()
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_published_chain_generates_postgresql_sql_without_legacy_orm() -> None:
    scripts = ScriptDirectory(str(Path(__file__).resolve().parents[1] / "alembic"))
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        for revision in reversed(list(scripts.walk_revisions())):
            revision.module.upgrade()
    sql = output.getvalue()
    for name in Base.metadata.tables:
        assert f"CREATE TABLE {name}" in sql
    assert "CREATE TABLE customers" in sql
    assert "CREATE TYPE loading_status AS ENUM" in sql
    assert "ALTER TABLE drivers ALTER COLUMN line_user_id DROP NOT NULL" in sql
    assert "COMMENT ON COLUMN routes.total_distance" in sql


def test_current_metadata_comparison_tolerates_only_retained_historical_tables() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            Base.metadata.create_all(connection)
            connection.execute(text("CREATE TABLE customers (id INTEGER PRIMARY KEY)"))
            assert current_metadata_diff(connection) == []
            connection.execute(text("CREATE TABLE unexpected_table (id INTEGER PRIMARY KEY)"))
            assert any(
                diff[0] == "remove_table" and diff[1].name == "unexpected_table"
                for diff in current_metadata_diff(connection)
            )
            connection.execute(text("DROP TABLE unexpected_table"))
            connection.execute(text("DROP TABLE experiment_metrics"))
            assert any(
                diff[0] == "add_table" and diff[1].name == "experiment_metrics"
                for diff in current_metadata_diff(connection)
            )
    finally:
        engine.dispose()
