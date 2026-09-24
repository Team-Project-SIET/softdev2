import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from pathlib import Path
from threading import Barrier, Event
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, func, inspect, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.config import get_settings
from app.customer.model import Customer
from app.database import models as _models  # noqa: F401
from app.database.base import Base
from app.driver.model import Driver
from app.packing.model import LoadingPlan
from app.packing.repository import PackingRepository
from app.packing.service import PackingService
from app.routing.model import Route
from app.routing.optimizer import CVRPOptimizer
from app.routing.repository import RoutingRepository
from app.routing.schemas import Coordinates, RoutingPlan
from app.routing.service import RoutingService, StaleRoutingPlanError
from app.shipment.model import Package, Shipment, ShipmentPriority, ShipmentStatus
from app.vehicle.model import Vehicle, VehicleStatus


class ZeroDistanceProvider:
    def distance(self, origin: Coordinates, destination: Coordinates) -> float:
        return 0.0


@pytest.fixture
def postgres_factory(
    request: pytest.FixtureRequest,
) -> sessionmaker[Session]:
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


def test_postgresql_migrations_and_concurrent_saves(
    postgres_factory: sessionmaker[Session],
) -> None:
    engine = postgres_factory.kw["bind"]
    scripts = ScriptDirectory("alembic")
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            for revision in ("0001", "0002", "0003", "0004", "0005", "0006"):
                scripts.get_revision(revision).module.upgrade()
        columns = {column["name"]: column for column in inspect(connection).get_columns("drivers")}
        assert columns["line_user_id"]["nullable"]
        assert compare_metadata(context, Base.metadata) == []

    with postgres_factory.begin() as session:
        customer = Customer(
            name="Concurrent Customer",
            phone="123",
            address="Address",
            latitude=Decimal("1"),
            longitude=Decimal("1"),
        )
        vehicle = Vehicle(
            name="Concurrent Van",
            width=180,
            length=300,
            height=180,
            max_weight=100,
            status=VehicleStatus.AVAILABLE,
        )
        shipment = Shipment(
            customer=customer,
            delivery_date=date(2026, 1, 1),
            priority=ShipmentPriority.NORMAL,
            status=ShipmentStatus.PENDING,
            packages=[Package(width=10, length=10, height=10, weight=10)],
        )
        session.add_all([vehicle, shipment])
        session.flush()
        shipment_id, vehicle_id = shipment.id, vehicle.id

    service = RoutingService(
        session_factory=postgres_factory,
        optimizer=CVRPOptimizer(ZeroDistanceProvider(), time_limit_seconds=1),
        depot=Coordinates(latitude=0, longitude=0),
    )
    plan = service.optimize([shipment_id], [vehicle_id])
    start = Barrier(2)

    def save_competing_preview():
        start.wait(timeout=5)
        return service.save_plan(plan)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(save_competing_preview) for _ in range(2)]
        outcomes = []
        for future in futures:
            try:
                outcomes.append(future.result(timeout=15))
            except StaleRoutingPlanError:
                outcomes.append("stale")
    assert sum(outcome == "stale" for outcome in outcomes) == 1

    with postgres_factory() as session:
        assert session.scalar(select(func.count()).select_from(Route)) == 1
        assert session.get(Shipment, shipment_id).status is ShipmentStatus.PLANNED
        route_id = session.scalar(select(Route.id))
        package_id = session.scalar(select(Package.id).where(Package.shipment_id == shipment_id))

    draft = PackingService(session_factory=postgres_factory).optimize(route_id)
    locked = Event()
    release = Event()
    writer_started = Event()
    writer_committed = Event()

    class PausingPackingRepository(PackingRepository):
        def lock_route_sources(self, session: Session, route_id: int) -> Route:
            route = super().lock_route_sources(session, route_id)
            locked.set()
            if not release.wait(timeout=5):
                raise RuntimeError("timed out waiting to release loading source locks")
            return route

    packing = PackingService(
        session_factory=postgres_factory, repository=PausingPackingRepository()
    )

    def change_package_weight() -> None:
        if not locked.wait(timeout=5):
            raise RuntimeError("loading save never locked its sources")
        writer_started.set()
        with postgres_factory.begin() as session:
            session.execute(update(Package).where(Package.id == package_id).values(weight=11))
        writer_committed.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        saving = executor.submit(packing.save_plan, draft)
        assert locked.wait(timeout=5)
        updating = executor.submit(change_package_weight)
        assert writer_started.wait(timeout=5)
        assert not writer_committed.wait(timeout=0.25)
        release.set()
        saved = saving.result(timeout=10)
        updating.result(timeout=10)

    with postgres_factory() as session:
        assert session.scalar(select(func.count()).select_from(LoadingPlan)) == 1
        assert session.get(LoadingPlan, saved.loading_plan_id).total_loaded_weight == 10
        assert session.get(Package, package_id).weight == 11


def _migrate_for_concurrency(postgres_factory: sessionmaker[Session]) -> None:
    scripts = ScriptDirectory("alembic")
    with postgres_factory.kw["bind"].begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            for revision in ("0001", "0002", "0003", "0004", "0005", "0006"):
                scripts.get_revision(revision).module.upgrade()


def _route_preview(
    postgres_factory: sessionmaker[Session], *, with_driver: bool = False
) -> tuple[RoutingService, RoutingPlan, int, int, int | None]:
    _migrate_for_concurrency(postgres_factory)
    with postgres_factory.begin() as session:
        customer = Customer(
            name="Race Customer",
            phone="123",
            address="Address",
            latitude=Decimal("1"),
            longitude=Decimal("1"),
        )
        vehicle = Vehicle(
            name="Race Van",
            width=180,
            length=300,
            height=180,
            max_weight=100,
            status=VehicleStatus.AVAILABLE,
        )
        shipment = Shipment(
            customer=customer,
            delivery_date=date(2026, 1, 1),
            priority=ShipmentPriority.NORMAL,
            status=ShipmentStatus.PENDING,
            packages=[Package(width=10, length=10, height=10, weight=10)],
        )
        session.add_all([vehicle, shipment])
        session.flush()
        driver_id = None
        if with_driver:
            driver = Driver(name="Race Driver", phone="123456", vehicle_id=vehicle.id)
            session.add(driver)
            session.flush()
            driver_id = driver.id
        shipment_id, vehicle_id = shipment.id, vehicle.id
    service = RoutingService(
        session_factory=postgres_factory,
        optimizer=CVRPOptimizer(ZeroDistanceProvider(), time_limit_seconds=1),
        depot=Coordinates(latitude=0, longitude=0),
    )
    return (
        service,
        service.optimize([shipment_id], [vehicle_id]),
        shipment_id,
        vehicle_id,
        driver_id,
    )


def test_postgresql_driver_reassignment_during_route_save_is_rejected(
    postgres_factory: sessionmaker[Session],
) -> None:
    service, plan, shipment_id, _, driver_id = _route_preview(postgres_factory, with_driver=True)
    assert driver_id is not None
    looked_up = Event()
    release = Event()

    class PausingRoutingRepository(RoutingRepository):
        def _candidate_driver_ids(self, session: Session, vehicle_id: int) -> list[int]:
            ids = super()._candidate_driver_ids(session, vehicle_id)
            looked_up.set()
            if not release.wait(timeout=5):
                raise RuntimeError("timed out waiting to recheck driver assignment")
            return ids

    service.repository = PausingRoutingRepository()
    with ThreadPoolExecutor(max_workers=2) as executor:
        saving = executor.submit(service.save_plan, plan)
        try:
            assert looked_up.wait(timeout=5)
            changing = executor.submit(lambda: _reassign_driver(postgres_factory, driver_id))
            changing.result(timeout=5)
        finally:
            release.set()
        with pytest.raises(StaleRoutingPlanError, match="driver assignment"):
            saving.result(timeout=10)

    with postgres_factory() as session:
        assert session.get(Driver, driver_id).vehicle_id is None
        assert session.get(Shipment, shipment_id).status is ShipmentStatus.PENDING
        assert session.scalar(select(func.count()).select_from(Route)) == 0


def _reassign_driver(postgres_factory: sessionmaker[Session], driver_id: int) -> None:
    with postgres_factory.begin() as session:
        session.execute(update(Driver).where(Driver.id == driver_id).values(vehicle_id=None))


def test_postgresql_shipment_writer_wins_before_route_save_lock(
    postgres_factory: sessionmaker[Session],
) -> None:
    service, plan, shipment_id, _, _ = _route_preview(postgres_factory)
    writer_locked = Event()
    release_writer = Event()
    save_entered = Event()

    class SignalingRoutingRepository(RoutingRepository):
        def lock_plan_sources(
            self, session: Session, shipment_ids: set[int], vehicle_ids: set[int]
        ) -> tuple[list[Shipment], list[Vehicle]]:
            save_entered.set()
            return super().lock_plan_sources(session, shipment_ids, vehicle_ids)

    service.repository = SignalingRoutingRepository()

    def cancel_shipment() -> None:
        with postgres_factory.begin() as session:
            session.execute(
                update(Shipment)
                .where(Shipment.id == shipment_id)
                .values(status=ShipmentStatus.CANCELLED)
            )
            writer_locked.set()
            if not release_writer.wait(timeout=5):
                raise RuntimeError("timed out waiting to commit cancellation")

    with ThreadPoolExecutor(max_workers=2) as executor:
        writing = executor.submit(cancel_shipment)
        assert writer_locked.wait(timeout=5)
        saving = executor.submit(service.save_plan, plan)
        try:
            assert save_entered.wait(timeout=5)
            assert not saving.done()
        finally:
            release_writer.set()
        writing.result(timeout=10)
        with pytest.raises(StaleRoutingPlanError, match="no longer pending"):
            saving.result(timeout=10)

    with postgres_factory() as session:
        assert session.get(Shipment, shipment_id).status is ShipmentStatus.CANCELLED
        assert session.scalar(select(func.count()).select_from(Route)) == 0


def test_postgresql_package_insert_during_packing_save_rejects_preview(
    postgres_factory: sessionmaker[Session],
) -> None:
    service, plan, shipment_id, _, _ = _route_preview(postgres_factory)
    route_id = service.save_plan(plan).route_ids[0]
    packing = PackingService(session_factory=postgres_factory)
    draft = packing.optimize(route_id)
    inserted = Event()
    release_writer = Event()
    save_entered = Event()

    class SignalingPackingRepository(PackingRepository):
        def lock_route_sources(self, session: Session, route_id: int) -> Route:
            save_entered.set()
            return super().lock_route_sources(session, route_id)

    packing.repository = SignalingPackingRepository()

    def insert_package() -> None:
        with postgres_factory.begin() as session:
            session.add(Package(shipment_id=shipment_id, width=5, length=5, height=5, weight=1))
            session.flush()
            inserted.set()
            if not release_writer.wait(timeout=5):
                raise RuntimeError("timed out waiting to commit package insert")

    with ThreadPoolExecutor(max_workers=2) as executor:
        writing = executor.submit(insert_package)
        assert inserted.wait(timeout=5)
        saving = executor.submit(packing.save_plan, draft)
        try:
            assert save_entered.wait(timeout=5)
            assert not saving.done()
        finally:
            release_writer.set()
        writing.result(timeout=10)
        with pytest.raises(ValueError, match="packages changed"):
            saving.result(timeout=10)

    with postgres_factory() as session:
        assert session.scalar(select(func.count()).select_from(Package)) == 2
        assert session.scalar(select(func.count()).select_from(LoadingPlan)) == 0


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


def _upgrade_isolated(config: Config, engine, revision: str) -> None:
    with engine.begin() as connection:
        assert connection.scalar(text("SELECT current_schema()")) != "public"
        config.attributes["connection"] = connection
        try:
            command.upgrade(config, revision)
        finally:
            del config.attributes["connection"]


def test_existing_0002_and_fresh_postgresql_upgrades_match(
    postgres_factory: sessionmaker[Session],
) -> None:
    """Run actual Alembic upgrades through both supported PostgreSQL paths."""

    legacy_engine = postgres_factory.kw["bind"]
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))

    _upgrade_isolated(config, legacy_engine, "0002")
    with legacy_engine.connect() as connection:
        columns = {column["name"]: column for column in inspect(connection).get_columns("routes")}
        stop_columns = {
            column["name"]: column for column in inspect(connection).get_columns("route_stops")
        }
        assert columns["total_distance"].get("comment") is None
        assert columns["total_weight"].get("comment") is None
        assert stop_columns["distance_from_previous"].get("comment") is None
    _upgrade_isolated(config, legacy_engine, "0004")
    with legacy_engine.connect() as connection:
        before_comments = _schema_signature(connection)
    _upgrade_isolated(config, legacy_engine, "head")

    with legacy_engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0006"
        legacy_signature = _schema_signature(connection)
        legacy_tables = {table: legacy_signature[table] for table in before_comments}
        assert _without_column_comments(legacy_tables) == _without_column_comments(before_comments)
        assert set(legacy_signature) - set(before_comments) == {
            "experiment_scenarios",
            "planning_strategies",
            "experiment_runs",
            "simulation_runs",
            "experiment_metrics",
        }
        assert _column_comments(legacy_signature, "routes")["total_distance"] == "Kilometers"
        assert _column_comments(legacy_signature, "routes")["total_weight"] == "Kilograms"
        assert (
            _column_comments(legacy_signature, "route_stops")["distance_from_previous"]
            == "Kilometers"
        )
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []

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
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0006"
            assert _schema_signature(connection) == legacy_signature
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    finally:
        if fresh_engine is not None:
            fresh_engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{fresh_schema}" CASCADE'))
        admin_engine.dispose()
