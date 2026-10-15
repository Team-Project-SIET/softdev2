"""Historical driver migration coverage without retired runtime ORM models."""

from io import StringIO
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text


def driver_migration():
    scripts = ScriptDirectory(str(Path(__file__).resolve().parents[1] / "alembic"))
    return scripts.get_revision("0004").module


def create_historical_schema(connection) -> None:
    scripts = ScriptDirectory(str(Path(__file__).resolve().parents[1] / "alembic"))
    for revision in ("0001", "0002", "0003", "0004"):
        scripts.get_revision(revision).module.upgrade()


def test_driver_line_id_migration_round_trip() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                create_historical_schema(connection)
                before = inspect(connection).get_columns("drivers")
                driver_migration().downgrade()
                line_column = next(
                    column
                    for column in inspect(connection).get_columns("drivers")
                    if column["name"] == "line_user_id"
                )
                assert not line_column["nullable"]
                driver_migration().upgrade()
                after = inspect(connection).get_columns("drivers")
                assert [(c["name"], str(c["type"]), c["nullable"]) for c in after] == [
                    (c["name"], str(c["type"]), c["nullable"]) for c in before
                ]
    finally:
        engine.dispose()


def test_downgrade_refuses_to_invent_line_ids() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                create_historical_schema(connection)
                connection.execute(
                    text(
                        "INSERT INTO drivers (name, phone, line_user_id) "
                        "VALUES ('No LINE', '123', NULL)"
                    )
                )
                with pytest.raises(RuntimeError, match="assign LINE user IDs"):
                    driver_migration().downgrade()
            assert connection.scalar(text("SELECT line_user_id FROM drivers")) is None
    finally:
        engine.dispose()


def test_driver_migration_generates_postgresql_alter() -> None:
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        driver_migration().upgrade()
    assert "ALTER TABLE drivers ALTER COLUMN line_user_id DROP NOT NULL" in output.getvalue()
