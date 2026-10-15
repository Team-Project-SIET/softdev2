"""Current PostgreSQL storage and published migration compatibility coverage."""

import os
import subprocess
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

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
from sqlalchemy import create_engine, func, insert, inspect, select, text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.config import get_settings
from app.experiments.domain import (
    ExecutionFailureCode,
    ExecutionMode,
    ExperimentConfig,
    ScenarioConfig,
)
from app.experiments.model import (
    ExperimentRunRecord,
    LiveTelemetrySessionRecord,
    TelemetryObservationRecord,
)
from app.experiments.repository import ExperimentRepository
from app.experiments.strategies import BaselineStrategy


def test_telemetry_migration_preserves_history_and_downgrades(
    postgres_factory: sessionmaker[Session],
) -> None:
    engine = postgres_factory.kw["bind"]
    scripts = ScriptDirectory("alembic")
    migration = scripts.get_revision("0007").module
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            for revision in ("0001", "0002", "0003", "0004", "0005", "0006"):
                scripts.get_revision(revision).module.upgrade()
            connection.execute(
                text(
                    "INSERT INTO experiment_scenarios "
                    "(id, identifier, version, openttd_config) VALUES (1, 'old', '1', '')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO planning_strategies (id, identifier, version) "
                    "VALUES (1, 'old', '1')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO experiment_runs "
                    "(id, scenario_id, strategy_id, strategy_configuration, ai_configuration, "
                    "openttd_version, opengfx_version, seed, duration_days, started_at, status) "
                    "VALUES (1, 1, 1, '{}', '{}', '13.4', '7.1', 7, 30, now(), 'succeeded')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO simulation_runs "
                    "(id, experiment_run_id, simulation_date, savegame_version) "
                    "VALUES (1, 1, '1950-01-31', 1)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO experiment_metrics "
                    "(id, simulation_run_id, name, value, unit) "
                    "VALUES (1, 1, 'company_money', 123.0000, 'GBP')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO customers (id, name, phone, address, latitude, longitude) "
                    "VALUES (1, 'legacy', '123', 'address', 1, 1)"
                )
            )
            before_tables = set(inspect(connection).get_table_names())
            migration.upgrade()
            assert (
                connection.scalar(text("SELECT execution_mode FROM experiment_runs WHERE id=1"))
                == "batch"
            )
            assert connection.scalar(
                text("SELECT value FROM experiment_metrics WHERE id=1")
            ) == Decimal("123.0000")
            assert connection.scalar(text("SELECT name FROM customers WHERE id=1")) == "legacy"
            assert connection.scalar(
                text("SELECT simulation_date FROM simulation_runs WHERE id=1")
            ) == date(1950, 1, 31)
            scripts.get_revision("0008").module.upgrade()
            assert current_metadata_diff(connection) == []
            scripts.get_revision("0008").module.downgrade()
            connection.execute(
                text(
                    "INSERT INTO live_telemetry_sessions "
                    "(experiment_run_id, telemetry_status) VALUES (1, 'pending')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO telemetry_observations "
                    "(experiment_run_id, sequence, connection_epoch, received_at, source, "
                    "schema_version, kind, date_quality, payload) "
                    "VALUES (1, 1, 0, now(), 'live_runtime', 1, 'diagnostic', 'unknown', '{}')"
                )
            )
            migration.downgrade()
            assert set(inspect(connection).get_table_names()) == before_tables
            assert "live_telemetry_sessions" not in inspect(connection).get_table_names()
            assert "telemetry_observations" not in inspect(connection).get_table_names()
            assert "execution_mode" not in {
                column["name"] for column in inspect(connection).get_columns("experiment_runs")
            }
            assert connection.scalar(
                text("SELECT value FROM experiment_metrics WHERE id=1")
            ) == Decimal("123.0000")
            assert connection.scalar(
                text("SELECT simulation_date FROM simulation_runs WHERE id=1")
            ) == date(1950, 1, 31)
            assert connection.scalar(text("SELECT name FROM customers WHERE id=1")) == "legacy"


def test_postgresql_telemetry_storage_constraints_and_cascade(
    postgres_factory: sessionmaker[Session],
) -> None:
    engine = postgres_factory.kw["bind"]
    scripts = ScriptDirectory("alembic")
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            for revision in ("0001", "0002", "0003", "0004", "0005", "0006", "0007", "0008"):
                scripts.get_revision(revision).module.upgrade()
        indexes = {
            index["name"]: index
            for index in inspect(connection).get_indexes("telemetry_observations")
        }
        assert indexes["ix_telemetry_observations_run_received_sequence"]["column_names"] == [
            "experiment_run_id",
            "received_at",
            "sequence",
        ]
        assert indexes["ix_telemetry_observations_run_company_day_sequence"]["column_names"] == [
            "experiment_run_id",
            "company_id",
            "game_day",
            "sequence",
        ]
        columns = {
            column["name"]: column
            for column in inspect(connection).get_columns("telemetry_observations")
        }
        assert columns["payload"]["type"].__class__.__name__ == "JSONB"
        assert inspect(connection).get_pk_constraint("telemetry_observations")[
            "constrained_columns"
        ] == ["experiment_run_id", "sequence"]

    scenario = ScenarioConfig(identifier="schema-test", version="1")
    planning, ai = BaselineStrategy().configure(scenario)
    config = ExperimentConfig(
        scenario=scenario,
        planning=planning,
        ai=ai,
        openttd_version="13.4",
        opengfx_version="7.1",
        seed=5,
        duration_days=30,
    )
    with postgres_factory.begin() as session:
        run_id = ExperimentRepository().create_run(
            session,
            config,
            datetime(2026, 1, 1, tzinfo=UTC),
            execution_mode=ExecutionMode.LIVE,
            execution_metadata={"target_day": 250},
        )
        session.add(
            LiveTelemetrySessionRecord(experiment_run_id=run_id, telemetry_status="pending")
        )
    received_at = datetime(2026, 1, 1, tzinfo=UTC)
    valid = dict(
        experiment_run_id=run_id,
        connection_epoch=1,
        received_at=received_at,
        source="openttd_admin",
        schema_version=1,
        protocol_version=1,
        kind="company_economy",
        company_id=0,
        game_day=250,
        date_context_sequence=1,
        date_quality="preceding_date",
        payload={"money": -1234567890123},
    )
    with postgres_factory.begin() as session:
        session.execute(
            insert(TelemetryObservationRecord), [dict(valid, sequence=1), dict(valid, sequence=2)]
        )
        session.execute(
            insert(TelemetryObservationRecord).values(
                {
                    **valid,
                    "sequence": 4,
                    "kind": "date",
                    "company_id": None,
                    "date_context_sequence": None,
                    "date_quality": "packet_date",
                    "payload": {"game_day": 250},
                }
            )
        )
        session.execute(
            insert(TelemetryObservationRecord).values(
                {
                    **valid,
                    "sequence": 5,
                    "connection_epoch": 0,
                    "source": "live_runtime",
                    "kind": "diagnostic",
                    "company_id": None,
                    "game_day": None,
                    "date_context_sequence": None,
                    "date_quality": "unknown",
                    "payload": {"code": "startup"},
                }
            )
        )
        session.execute(
            insert(TelemetryObservationRecord).values(
                {
                    **valid,
                    "sequence": 6,
                    "kind": "diagnostic",
                    "company_id": None,
                    "game_day": None,
                    "date_context_sequence": None,
                    "date_quality": "unknown",
                    "payload": {"code": "unsupported_admin_packet"},
                }
            )
        )
    with postgres_factory() as session:
        observations = session.scalars(
            select(TelemetryObservationRecord).order_by(TelemetryObservationRecord.sequence)
        ).all()
        assert [observation.sequence for observation in observations] == [1, 2, 4, 5, 6]
        assert observations[0].payload == {"money": -1234567890123}
        telemetry_session = session.get(LiveTelemetrySessionRecord, run_id)
        assert telemetry_session is not None
        assert telemetry_session.observations[0].experiment_run_id == run_id
        run = session.get(ExperimentRunRecord, run_id)
        assert run is not None
        assert run.execution_mode == "live"
        assert run.execution_metadata == {"target_day": 250}
        assert run.simulation is None
        assert (
            session.scalar(
                text(
                    "SELECT pg_typeof(execution_metadata)::text FROM experiment_runs WHERE id=:id"
                ),
                {"id": run_id},
            )
            == "jsonb"
        )

    bad_cases = (
        (dict(sequence=1), "pk_telemetry_observations"),
        (dict(sequence=0), "sequence_positive"),
        (dict(schema_version=0), "schema_version_positive"),
        (dict(connection_epoch=-1), "epoch_nonnegative"),
        (dict(connection_epoch=0), "measurement_epoch_positive"),
        (dict(source="other"), "source_"),
        (dict(source="live_runtime"), "source_kind_valid"),
        (dict(kind="other"), "kind_valid"),
        (dict(date_quality="packet_date"), "packet_date_kind_valid"),
        (dict(date_quality="other"), "date_quality_valid"),
        (dict(company_id=15), "company_id_valid"),
        (dict(kind="date", company_id=0), "date_shape_valid"),
        (dict(kind="date", company_id=None), "date_shape_valid"),
        (dict(kind="company_info", company_id=None), "company_shape_valid"),
        (dict(date_quality="unknown", game_day=250), "unknown_date_context_empty"),
        (dict(payload=[1, 2]), "payload_object"),
        (dict(payload="text"), "payload_object"),
    )
    for overrides, constraint in bad_cases:
        with postgres_factory() as session:
            with pytest.raises(IntegrityError, match=constraint):
                with session.begin():
                    session.execute(
                        insert(TelemetryObservationRecord).values(
                            {**valid, "sequence": 3, **overrides}
                        )
                    )

    rejected_updates = (
        ("UPDATE experiment_runs SET execution_mode='other' WHERE id=:id", "execution_mode_valid"),
        ("UPDATE experiment_runs SET failure_code='other' WHERE id=:id", "failure_code_valid"),
        (
            "UPDATE experiment_runs SET execution_metadata='[]'::jsonb WHERE id=:id",
            "execution_metadata_object",
        ),
        (
            "UPDATE live_telemetry_sessions SET telemetry_status='other' "
            "WHERE experiment_run_id=:id",
            "telemetry_status_valid",
        ),
        (
            "UPDATE live_telemetry_sessions SET received_count=-1 WHERE experiment_run_id=:id",
            "counts_nonnegative",
        ),
    )
    for statement, constraint in rejected_updates:
        with postgres_factory() as session:
            with pytest.raises(IntegrityError, match=constraint):
                with session.begin():
                    session.execute(text(statement), {"id": run_id})

    with postgres_factory() as session:
        with pytest.raises(IntegrityError, match="payload_object"):
            with session.begin():
                session.execute(
                    text(
                        "UPDATE telemetry_observations SET payload='null'::jsonb "
                        "WHERE experiment_run_id=:id AND sequence=1"
                    ),
                    {"id": run_id},
                )

    with postgres_factory() as session:
        with pytest.raises(DataError, match="value too long"):
            with session.begin():
                session.execute(
                    text(
                        "UPDATE live_telemetry_sessions SET error_summary=repeat('x', 1025) "
                        "WHERE experiment_run_id=:id"
                    ),
                    {"id": run_id},
                )

    with postgres_factory() as session:
        with pytest.raises(IntegrityError, match="fk_telemetry_observations"):
            with session.begin():
                session.execute(
                    insert(TelemetryObservationRecord).values(
                        {**valid, "experiment_run_id": run_id + 1000, "sequence": 1}
                    )
                )

    with postgres_factory() as session:
        with pytest.raises(IntegrityError, match="pk_live_telemetry_sessions"):
            with session.begin():
                session.add(
                    LiveTelemetrySessionRecord(experiment_run_id=run_id, telemetry_status="pending")
                )
    with postgres_factory() as session:
        with pytest.raises(IntegrityError, match="fk_live_telemetry_sessions"):
            with session.begin():
                session.add(
                    LiveTelemetrySessionRecord(
                        experiment_run_id=run_id + 1000, telemetry_status="pending"
                    )
                )
    with postgres_factory.begin() as session:
        ExperimentRepository().fail_run(
            session,
            run_id,
            "failure",
            datetime(2026, 1, 2, tzinfo=UTC),
            failure_code=ExecutionFailureCode.STARTUP_FAILURE,
        )
    with postgres_factory() as session:
        run = session.get(ExperimentRunRecord, run_id)
        assert run is not None
        assert run.failure_code == "startup_failure"
    with postgres_factory.begin() as session:
        session.execute(text("DELETE FROM experiment_runs WHERE id=:id"), {"id": run_id})
    with postgres_factory() as session:
        assert session.get(LiveTelemetrySessionRecord, run_id) is None
        assert session.scalar(select(func.count()).select_from(TelemetryObservationRecord)) == 0


def _schema_signature(connection) -> dict:
    inspector = inspect(connection)
    signature = {}
    for table in sorted(inspector.get_table_names()):
        if table == "alembic_version":
            continue
        primary_key = inspector.get_pk_constraint(table)
        signature[table] = {
            "columns": [
                (
                    column["name"],
                    str(column["type"]),
                    column["nullable"],
                    column.get("default"),
                    column.get("comment"),
                )
                for column in inspector.get_columns(table)
            ],
            "primary_key": (
                primary_key["name"],
                tuple(primary_key["constrained_columns"]),
            ),
            "foreign_keys": sorted(
                (
                    key["name"],
                    tuple(key["constrained_columns"]),
                    key["referred_table"],
                    tuple(key["referred_columns"]),
                    key.get("options", {}).get("ondelete"),
                )
                for key in inspector.get_foreign_keys(table)
            ),
            "unique_constraints": sorted(
                (key["name"], tuple(key["column_names"]))
                for key in inspector.get_unique_constraints(table)
            ),
            "check_constraints": sorted(
                (key["name"], key["sqltext"]) for key in inspector.get_check_constraints(table)
            ),
            "indexes": sorted(
                (index["name"], tuple(index["column_names"]), index["unique"])
                for index in inspector.get_indexes(table)
            ),
        }
    return signature


def _without_column_comments(signature: dict) -> dict:
    return {
        table: {
            **details,
            "columns": [column[:-1] for column in details["columns"]],
        }
        for table, details in signature.items()
    }


def _column_comments(signature: dict, table: str) -> dict[str, str | None]:
    return {column[0]: column[-1] for column in signature[table]["columns"]}


def test_existing_0002_and_fresh_postgresql_upgrades_match(
    postgres_factory: sessionmaker[Session],
) -> None:
    """Run actual Alembic upgrades through both supported PostgreSQL paths."""

    legacy_engine = postgres_factory.kw["bind"]
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))

    upgrade_isolated(config, legacy_engine, "0002")
    with legacy_engine.connect() as connection:
        columns = {column["name"]: column for column in inspect(connection).get_columns("routes")}
        stop_columns = {
            column["name"]: column for column in inspect(connection).get_columns("route_stops")
        }
        assert columns["total_distance"].get("comment") is None
        assert columns["total_weight"].get("comment") is None
        assert stop_columns["distance_from_previous"].get("comment") is None
    upgrade_isolated(config, legacy_engine, "0004")
    with legacy_engine.connect() as connection:
        before_comments = _schema_signature(connection)
    upgrade_isolated(config, legacy_engine, "0006")
    upgrade_isolated(config, legacy_engine, "head")

    with legacy_engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0008"
        legacy_signature = _schema_signature(connection)
        legacy_tables = {table: legacy_signature[table] for table in before_comments}
        assert _without_column_comments(legacy_tables) == _without_column_comments(before_comments)
        assert set(legacy_signature) - set(before_comments) == {
            "experiment_scenarios",
            "planning_strategies",
            "experiment_runs",
            "simulation_runs",
            "experiment_metrics",
            "live_telemetry_sessions",
            "telemetry_observations",
            "plan_evaluations",
        }
        assert _column_comments(legacy_signature, "routes")["total_distance"] == "Kilometers"
        assert _column_comments(legacy_signature, "routes")["total_weight"] == "Kilograms"
        assert (
            _column_comments(legacy_signature, "route_stops")["distance_from_previous"]
            == "Kilometers"
        )
        assert current_metadata_diff(connection) == []

    with legacy_engine.begin() as connection:
        config.attributes["connection"] = connection
        try:
            command.downgrade(config, "0006")
        finally:
            del config.attributes["connection"]
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0006"
        assert "execution_mode" not in {
            column["name"] for column in inspect(connection).get_columns("experiment_runs")
        }
        assert "live_telemetry_sessions" not in inspect(connection).get_table_names()
    upgrade_isolated(config, legacy_engine, "head")
    with legacy_engine.connect() as connection:
        assert _schema_signature(connection) == legacy_signature

    fresh_schema = "logistics_test_" + uuid4().hex
    admin_engine = create_engine(str(get_settings().database_url))
    fresh_engine = None
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{fresh_schema}"'))
        fresh_engine = create_engine(
            str(get_settings().database_url),
            connect_args={"options": f"-c search_path={fresh_schema}"},
        )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "alembic",
                "-c",
                str(Path(__file__).resolve().parents[1] / "alembic.ini"),
                "upgrade",
                "head",
            ],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "PGOPTIONS": f"-c search_path={fresh_schema}"},
            check=True,
            capture_output=True,
            text=True,
        )
        with fresh_engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0008"
            assert _schema_signature(connection) == legacy_signature
            assert current_metadata_diff(connection) == []
    finally:
        if fresh_engine is not None:
            fresh_engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{fresh_schema}" CASCADE'))
        admin_engine.dispose()
