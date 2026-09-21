from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.customer.model import Customer
from app.database.session import create_session
from app.driver.model import Driver
from app.shipment.model import Package, Shipment, ShipmentPriority, ShipmentStatus
from app.vehicle.model import Vehicle, VehicleStatus


def seed_database() -> bool:
    """Insert a small idempotent demo dataset.

    Returns ``True`` when rows were inserted and ``False`` when seed data already exists.
    """

    with create_session() as session, session.begin():
        if session.scalar(select(Customer.id).limit(1)) is not None:
            return False

        van = Vehicle(
            name="Van 01",
            width=Decimal("178.00"),
            length=Decimal("320.00"),
            height=Decimal("185.00"),
            max_weight=Decimal("1200.00"),
            status=VehicleStatus.AVAILABLE,
        )
        truck = Vehicle(
            name="Truck 01",
            width=Decimal("220.00"),
            length=Decimal("520.00"),
            height=Decimal("230.00"),
            max_weight=Decimal("3500.00"),
            status=VehicleStatus.AVAILABLE,
        )
        session.add_all([van, truck])
        session.flush()

        session.add_all(
            [
                Driver(
                    name="Anan Chaiyasit",
                    phone="081-555-0101",
                    line_user_id=None,
                    vehicle_id=van.id,
                ),
                Driver(
                    name="Mali Saelim",
                    phone="082-555-0102",
                    line_user_id=None,
                    vehicle_id=truck.id,
                ),
            ]
        )

        central_shop = Customer(
            name="Central Corner Shop",
            phone="02-555-1001",
            address="99 Sukhumvit Road, Bangkok",
            latitude=Decimal("13.736717"),
            longitude=Decimal("100.523186"),
        )
        riverside_cafe = Customer(
            name="Riverside Cafe",
            phone="02-555-1002",
            address="21 Charoen Krung Road, Bangkok",
            latitude=Decimal("13.724893"),
            longitude=Decimal("100.514266"),
        )
        session.add_all([central_shop, riverside_cafe])
        session.flush()

        today = date.today()
        session.add_all(
            [
                Shipment(
                    customer_id=central_shop.id,
                    delivery_date=today + timedelta(days=1),
                    priority=ShipmentPriority.HIGH,
                    status=ShipmentStatus.PENDING,
                    notes="Deliver before noon if possible.",
                    packages=[
                        Package(
                            width=Decimal("40"),
                            length=Decimal("60"),
                            height=Decimal("35"),
                            weight=Decimal("18.50"),
                            stackable=True,
                        ),
                        Package(
                            width=Decimal("30"),
                            length=Decimal("45"),
                            height=Decimal("25"),
                            weight=Decimal("9.25"),
                            stackable=True,
                        ),
                    ],
                ),
                Shipment(
                    customer_id=riverside_cafe.id,
                    delivery_date=today + timedelta(days=1),
                    priority=ShipmentPriority.NORMAL,
                    status=ShipmentStatus.PLANNED,
                    notes=None,
                    packages=[
                        Package(
                            width=Decimal("55"),
                            length=Decimal("70"),
                            height=Decimal("50"),
                            weight=Decimal("31.00"),
                            stackable=False,
                        )
                    ],
                ),
                Shipment(
                    customer_id=central_shop.id,
                    delivery_date=today + timedelta(days=2),
                    priority=ShipmentPriority.LOW,
                    status=ShipmentStatus.PENDING,
                    notes="Receiving desk on level 1.",
                    packages=[
                        Package(
                            width=Decimal("25"),
                            length=Decimal("30"),
                            height=Decimal("20"),
                            weight=Decimal("4.50"),
                            stackable=True,
                        )
                    ],
                ),
            ]
        )

    return True


def main() -> None:
    inserted = seed_database()
    print("Seed data inserted." if inserted else "Seed data already exists; nothing changed.")


if __name__ == "__main__":
    main()
