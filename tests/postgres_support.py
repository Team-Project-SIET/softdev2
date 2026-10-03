"""Shared isolated PostgreSQL fixtures and current-schema migration checks."""

from collections.abc import Generator
from typing import Any
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.config import get_settings
from app.database import models as _models  # noqa: F401
from app.database.base import Base

# Published migrations still create these tables. They are deliberately outside
# current ORM metadata; schema retirement is a separate, data-retention task.
LEGACY_TABLES = frozenset(
    {
        "customers",
        "drivers",
        "vehicles",
        "shipments",
        "packages",
        "routes",
        "route_stops",
        "loading_plans",
        "package_placements",
    }
)


def current_metadata_diff(connection: Connection) -> list[Any]:
    """Compare all current objects while tolerating retained historical tables."""
    context = MigrationContext.configure(
        connection,
        opts={
            "include_object": lambda obj, name, kind, reflected, compare_to: (
                kind != "table" or name not in LEGACY_TABLES | {"alembic_version"}
            ),
        },
    )
    return compare_metadata(context, Base.metadata)


@pytest.fixture
def postgres_factory(
    request: pytest.FixtureRequest,
) -> Generator[sessionmaker[Session]]:
    if not request.config.getoption("--run-postgres"):
        pytest.skip("pass --run-postgres to exercise an isolated PostgreSQL schema")
    try:
        url = str(get_settings().database_url)
    except Exception as exc:
        pytest.skip(f"PostgreSQL settings unavailable: {type(exc).__name__}")
    schema = "logistics_test_" + uuid4().hex
    admin_engine = create_engine(url)
    scoped_engine = None
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        scoped_engine = create_engine(url, connect_args={"options": f"-c search_path={schema}"})
        yield sessionmaker(bind=scoped_engine, expire_on_commit=False)
    finally:
        if scoped_engine is not None:
            scoped_engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


def upgrade_isolated(config: Config, engine: Engine, revision: str) -> None:
    with engine.begin() as connection:
        assert connection.scalar(text("SELECT current_schema()")) != "public"
        config.attributes["connection"] = connection
        try:
            command.upgrade(config, revision)
        finally:
            del config.attributes["connection"]
