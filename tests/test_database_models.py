import subprocess
import sys
from datetime import date

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session, configure_mappers, sessionmaker

from app.customer.model import Customer
from app.database import models, seed
from app.database.base import Base
from app.driver.model import Driver
from app.shipment.model import Package, Shipment


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
            "'LoadingPlan', 'PackagePlacement'}",
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

    assert len(shipments) == 3
    assert len(vehicles) == 2
    with session_factory() as session:
        assert {driver.line_user_id for driver in session.scalars(select(Driver))} == {None}


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
