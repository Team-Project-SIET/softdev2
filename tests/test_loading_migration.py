from io import StringIO
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from app.database import models
from app.database.base import Base


def loading_migration():
    scripts = ScriptDirectory(str(Path(__file__).resolve().parents[1] / "alembic"))
    return scripts.get_revision("0003").module


def test_loading_migration_upgrades_match_metadata_and_downgrades() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    new_tables = {models.LoadingPlan.__table__, models.PackagePlacement.__table__}
    old_tables = [table for table in Base.metadata.sorted_tables if table not in new_tables]
    try:
        with engine.begin() as connection:
            Base.metadata.create_all(connection, tables=old_tables)
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                loading_migration().upgrade()
                assert compare_metadata(context, Base.metadata) == []
                loading_migration().downgrade()
            assert set(inspect(connection).get_table_names()) == {t.name for t in old_tables}
    finally:
        engine.dispose()


def test_loading_migration_generates_postgresql_enum_and_tables() -> None:
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        loading_migration().upgrade()
        loading_migration().downgrade()
    sql = output.getvalue()
    assert "CREATE TYPE loading_status AS ENUM" in sql
    assert "CREATE TABLE loading_plans" in sql
    assert "CREATE TABLE package_placements" in sql
    assert "DROP TYPE loading_status" in sql
