from io import StringIO
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from app.database import models as _models  # noqa: F401
from app.database.base import Base
from app.driver.model import Driver


def driver_migration():
    scripts = ScriptDirectory(str(Path(__file__).resolve().parents[1] / "alembic"))
    return scripts.get_revision("0004").module


def test_driver_line_id_migration_round_trip_and_metadata_parity() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            Base.metadata.create_all(connection)
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                driver_migration().downgrade()
                line_column = next(
                    column
                    for column in inspect(connection).get_columns("drivers")
                    if column["name"] == "line_user_id"
                )
                assert not line_column["nullable"]
                driver_migration().upgrade()
                assert compare_metadata(context, Base.metadata) == []
    finally:
        engine.dispose()


def test_downgrade_refuses_to_invent_line_ids() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session, session.begin():
            session.add(Driver(name="No LINE", phone="123", line_user_id=None))
        with engine.begin() as connection:
            context = MigrationContext.configure(connection)
            with (
                Operations.context(context),
                pytest.raises(RuntimeError, match="assign LINE user IDs"),
            ):
                driver_migration().downgrade()
        with Session(engine) as session:
            assert session.scalar(select(Driver.line_user_id)) is None
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
