"""Freight history uses the migrated PostgreSQL schema; never touch public tables."""

import pytest
from alembic.config import Config
from sqlalchemy import text

from app.experiments.freight_history import FreightHistory
from tests.postgres_support import postgres_factory as postgres_factory
from tests.postgres_support import upgrade_isolated
from tests.test_freight_analytics import controlled_evaluations as controlled_evaluations


def test_postgres_freight_history_roundtrip_and_idempotency(
    postgres_factory, controlled_evaluations
):
    engine = postgres_factory.kw["bind"]
    upgrade_isolated(Config("alembic.ini"), engine, "head")
    history = FreightHistory.from_engine(engine)
    history.add(list(controlled_evaluations))
    history.add(list(controlled_evaluations))
    assert len(history.runs()) == 3
    assert history.runs()[2].model_dump(mode="json") == controlled_evaluations[2].model_dump(
        mode="json"
    )
    with pytest.raises(ValueError, match="different provenance"):
        history.add([controlled_evaluations[2].model_copy(update={"source_directory": "/changed"})])
    with engine.begin() as connection:
        assert connection.scalar(text("SELECT current_schema()")) != "public"
        assert connection.scalar(text("SELECT count(*) FROM freight_run_history")) == 3
