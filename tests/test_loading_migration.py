from io import StringIO
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect


def loading_migration():
    scripts = ScriptDirectory(str(Path(__file__).resolve().parents[1] / "alembic"))
    return scripts.get_revision("0003").module


def test_loading_migration_upgrades_and_downgrades() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with engine.begin() as connection:
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                scripts = ScriptDirectory(str(Path(__file__).resolve().parents[1] / "alembic"))
                for revision in ("0001", "0002"):
                    scripts.get_revision(revision).module.upgrade()
                before = set(inspect(connection).get_table_names())
                loading_migration().upgrade()
                assert set(inspect(connection).get_table_names()) == before | {
                    "loading_plans",
                    "package_placements",
                }
                assert {
                    fk["referred_table"]
                    for fk in inspect(connection).get_foreign_keys("package_placements")
                } == {"loading_plans", "packages"}
                assert {
                    fk["referred_table"]
                    for fk in inspect(connection).get_foreign_keys("loading_plans")
                } == {"routes", "vehicles"}
                loading_migration().downgrade()
            assert set(inspect(connection).get_table_names()) == before
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
