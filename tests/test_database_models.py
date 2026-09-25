import subprocess
import sys
from datetime import date

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session, configure_mappers, sessionmaker

from app.customer.model import Customer
from app.database import models, seed
from app.database.base import Base
from app.driver.model import Driver
from app.shipment.model import Package, Shipment, ShipmentStatus

ADDITIONAL_SHIPMENT_NOTES = {
    "Demo pantry restock: dry goods and cleaning supplies.",
    "Demo cafe restock: bottled drinks and coffee beans.",
    "Demo appliance delivery: keep the large carton upright.",
    "Demo cafe equipment: handle the grinder carton with care.",
    "Demo promotion stock: bulky display cartons.",
}


def test_session_boundary_registers_models_before_mapper_configuration() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from sqlalchemy.orm import configure_mappers; "
            "from app.database.session import create_session; "
            "from app.database.base import Base; "
            "configure_mappers(); "
            "assert {mapper.class_.__name__ for mapper in Base.registry.mappers} == "
            "{'Customer', 'Shipment', 'Package', 'Vehicle', 'Driver', 'Route', 'RouteStop', "
            "'LoadingPlan', 'PackagePlacement', 'ExperimentScenario', "
            "'PlanningStrategyRecord', 'ExperimentRunRecord', 'SimulationRunRecord', "
            "'ExperimentMetricRecord', 'LiveTelemetrySessionRecord', "
            "'TelemetryObservationRecord'}",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_all_models_share_registry_and_mappers_configure() -> None:
    expected_models = {
        models.Customer,
        models.Shipment,
        models.Package,
        models.Vehicle,
        models.Driver,
        models.Route,
        models.RouteStop,
        models.LoadingPlan,
        models.PackagePlacement,
        models.ExperimentScenario,
        models.PlanningStrategyRecord,
        models.ExperimentRunRecord,
        models.SimulationRunRecord,
        models.ExperimentMetricRecord,
        models.LiveTelemetrySessionRecord,
        models.TelemetryObservationRecord,
    }

    configure_mappers()

    assert {mapper.class_ for mapper in Base.registry.mappers} == expected_models
    assert all(mapper.registry is Base.registry for mapper in Base.registry.mappers)
    assert models.Route.driver.property.back_populates == "routes"
    assert models.Driver.routes.property.back_populates == "driver"


def test_seeded_shipments_and_vehicles_can_be_queried(
    session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    monkeypatch.setattr(seed, "create_session", session_factory)

    assert seed.seed_database() is True

    with session_factory() as session:
        shipments = session.scalars(select(models.Shipment)).all()
        vehicles = session.scalars(select(models.Vehicle)).all()
        drivers = session.scalars(select(Driver)).all()
        additional = [
            shipment for shipment in shipments if shipment.notes in ADDITIONAL_SHIPMENT_NOTES
        ]

        assert len(shipments) == 8
        assert len(vehicles) == 2
        assert len(drivers) == 2
        assert {driver.line_user_id for driver in drivers} == {None}
        assert session.scalar(select(func.count()).select_from(Customer)) == 2
        assert session.scalar(select(func.count()).select_from(Package)) == 20
        assert sum(shipment.status is ShipmentStatus.PENDING for shipment in shipments) == 7
        assert len(additional) == 5
        assert sum(len(shipment.packages) for shipment in additional) == 16
        assert {shipment.customer.name for shipment in additional} == {
            "Central Corner Shop",
            "Riverside Cafe",
        }
        for shipment in additional:
            assert shipment.status is ShipmentStatus.PENDING
            assert len(shipment.packages) >= 3
            assert sum(package.weight for package in shipment.packages) <= min(
                vehicle.max_weight for vehicle in vehicles
            )
            for package in shipment.packages:
                assert min(package.width, package.length, package.height, package.weight) > 0
                assert any(
                    package.width <= vehicle.width
                    and package.length <= vehicle.length
                    and package.height <= vehicle.height
                    for vehicle in vehicles
                )
        assert session.scalar(select(func.count()).select_from(models.RouteStop)) == 0


def test_seed_expands_existing_demo_data_without_changing_operational_records(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(seed, "create_session", session_factory)
    assert seed.seed_database() is True
    with session_factory.begin() as session:
        session.execute(delete(Shipment).where(Shipment.notes.in_(ADDITIONAL_SHIPMENT_NOTES)))
        original = session.scalars(select(Shipment).order_by(Shipment.id)).all()
        original[0].status = ShipmentStatus.CANCELLED
        driver = session.scalars(select(Driver).order_by(Driver.id)).first()
        assert driver is not None
        driver.line_user_id = "U" + "a" * 32
        route = models.Route(
            vehicle_id=driver.vehicle_id,
            driver_id=driver.id,
            total_distance=0,
            total_weight=31,
            stops=[
                models.RouteStop(
                    shipment_id=original[1].id,
                    customer_id=original[1].customer_id,
                    stop_order=1,
                    distance_from_previous=0,
                )
            ],
        )
        session.add(route)
        session.flush()
        original_rows = [(shipment.id, shipment.status, shipment.notes) for shipment in original]
        original_package_ids = set(session.scalars(select(Package.id)))
        route_id = route.id
        driver_id = driver.id
        stop_id = route.stops[0].id

    assert seed.seed_database() is True

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Shipment)) == 8
        assert session.scalar(select(func.count()).select_from(Package)) == 20
        assert (
            list(
                session.execute(
                    select(Shipment.id, Shipment.status, Shipment.notes)
                    .where(Shipment.id.in_(row[0] for row in original_rows))
                    .order_by(Shipment.id)
                )
            )
            == original_rows
        )
        assert original_package_ids.issubset(session.scalars(select(Package.id)))
        assert session.get(Driver, driver_id).line_user_id == "U" + "a" * 32
        assert session.scalar(select(func.count()).select_from(Customer)) == 2
        assert session.scalar(select(func.count()).select_from(models.Vehicle)) == 2
        assert session.scalar(select(func.count()).select_from(Driver)) == 2
        assert session.scalar(select(func.count()).select_from(models.Route)) == 1
        assert [
            (stop.id, stop.route_id, stop.shipment_id)
            for stop in session.scalars(select(models.RouteStop))
        ] == [(stop_id, route_id, original_rows[1][0])]
        additional = session.scalars(
            select(Shipment).where(Shipment.notes.in_(ADDITIONAL_SHIPMENT_NOTES))
        ).all()
        assert len(additional) == 5
        assert all(shipment.status is ShipmentStatus.PENDING for shipment in additional)


@pytest.mark.parametrize("status", [ShipmentStatus.PLANNED, ShipmentStatus.CANCELLED])
def test_repeated_seed_preserves_supplemental_shipment_status_and_date(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch, status: ShipmentStatus
) -> None:
    monkeypatch.setattr(seed, "create_session", session_factory)
    assert seed.seed_database() is True
    assert seed.seed_database() is False
    with session_factory.begin() as session:
        shipment = session.scalars(
            select(Shipment)
            .where(Shipment.notes.in_(ADDITIONAL_SHIPMENT_NOTES))
            .order_by(Shipment.id)
        ).first()
        assert shipment is not None
        shipment.status = status
        shipment.delivery_date = date(2020, 1, 1)
        shipment_id = shipment.id
        shipment_ids = set(session.scalars(select(Shipment.id)))
        package_ids = set(session.scalars(select(Package.id)))

    assert seed.seed_database() is False

    with session_factory() as session:
        assert set(session.scalars(select(Shipment.id))) == shipment_ids
        assert set(session.scalars(select(Package.id))) == package_ids
        shipment = session.get(Shipment, shipment_id)
        assert shipment.status is status
        assert shipment.delivery_date == date(2020, 1, 1)


def test_seed_does_not_add_demo_data_to_unrelated_customers(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(seed, "create_session", session_factory)
    with session_factory.begin() as session:
        session.add(
            Customer(
                name="Existing customer", phone="123", address="Address", latitude=0, longitude=0
            )
        )

    assert seed.seed_database() is False

    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Customer)) == 1
        for model in (Shipment, Package, models.Vehicle, Driver, models.Route, models.RouteStop):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_sqlite_fixture_enforces_foreign_keys(session_factory: sessionmaker[Session]) -> None:
    with session_factory.begin() as session:
        assert session.scalar(text("PRAGMA foreign_keys")) == 1
        customer = Customer(
            name="FK Customer", phone="123", address="Address", latitude=0, longitude=0
        )
        shipment = Shipment(customer=customer, delivery_date=date(2026, 1, 1))
        shipment.packages = [Package(width=1, length=1, height=1, weight=1)]
        session.add(shipment)
        session.flush()
        shipment_id = shipment.id

    with session_factory.begin() as session:
        session.execute(delete(Shipment).where(Shipment.id == shipment_id))

    with session_factory() as session:
        assert session.scalar(select(Package).where(Package.shipment_id == shipment_id)) is None
