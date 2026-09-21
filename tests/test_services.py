from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session, sessionmaker

from app.customer.model import Customer
from app.shipment.model import Package, Shipment, ShipmentPriority, ShipmentStatus
from app.shipment.service import ShipmentService
from app.vehicle.model import Vehicle, VehicleStatus
from app.vehicle.service import VehicleService


def test_shipment_service_builds_tui_summary(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory.begin() as session:
        customer = Customer(
            name="Test Customer",
            phone="123",
            address="Test address",
            latitude=Decimal("13.756331"),
            longitude=Decimal("100.501762"),
        )
        session.add(customer)
        session.flush()
        session.add(
            Shipment(
                customer_id=customer.id,
                delivery_date=date(2026, 1, 2),
                priority=ShipmentPriority.HIGH,
                status=ShipmentStatus.PENDING,
                notes=None,
                packages=[
                    Package(width=10, length=20, height=30, weight=Decimal("5.25")),
                    Package(width=20, length=20, height=20, weight=Decimal("7.75")),
                ],
            )
        )

    rows = ShipmentService(session_factory=session_factory).list_shipments()

    assert len(rows) == 1
    assert rows[0].customer_name == "Test Customer"
    assert rows[0].package_count == 2
    assert rows[0].total_weight == Decimal("13.00")


def test_vehicle_service_returns_pydantic_rows(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory.begin() as session:
        session.add(
            Vehicle(
                name="Test Van",
                width=178,
                length=320,
                height=185,
                max_weight=1200,
                status=VehicleStatus.AVAILABLE,
            )
        )

    rows = VehicleService(session_factory=session_factory).list_vehicles()

    assert len(rows) == 1
    assert rows[0].name == "Test Van"
    assert rows[0].status is VehicleStatus.AVAILABLE
