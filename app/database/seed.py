from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.customer.model import Customer
from app.database.session import create_session
from app.driver.model import Driver
from app.shipment.model import Package, Shipment, ShipmentPriority, ShipmentStatus
from app.vehicle.model import Vehicle, VehicleStatus


def seed_database() -> bool:
    """Insert the demo dataset and any missing sample shipments.

    Returns ``True`` when rows were inserted and ``False`` when seed data already exists.
    """

    with create_session() as session, session.begin():
        if session.scalar(select(Customer.id).limit(1)) is not None:
            return _seed_pending_shipments(session)

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

        _seed_pending_shipments(session)

    return True


def _seed_pending_shipments(session: Session) -> bool:
    """Extend existing demo customers without resetting previously seeded shipments."""

    customers = list(
        session.scalars(
            select(Customer)
            .where(Customer.name.in_(["Central Corner Shop", "Riverside Cafe"]))
            .order_by(Customer.id)
            .with_for_update()
        )
    )
    by_name = {customer.name: customer for customer in customers}
    if len(customers) != 2 or len(by_name) != 2:
        return False

    today = date.today()
    shipments = [
        Shipment(
            customer_id=by_name["Central Corner Shop"].id,
            delivery_date=today + timedelta(days=1),
            priority=ShipmentPriority.NORMAL,
            status=ShipmentStatus.PENDING,
            notes="Demo pantry restock: dry goods and cleaning supplies.",
            packages=[
                Package(width=40, length=60, height=35, weight=Decimal("18.50"), stackable=True),
                Package(width=40, length=60, height=35, weight=Decimal("17.75"), stackable=True),
                Package(width=30, length=45, height=25, weight=Decimal("9.25"), stackable=True),
                Package(width=50, length=60, height=45, weight=Decimal("22.00"), stackable=True),
            ],
        ),
        Shipment(
            customer_id=by_name["Riverside Cafe"].id,
            delivery_date=today + timedelta(days=1),
            priority=ShipmentPriority.HIGH,
            status=ShipmentStatus.PENDING,
            notes="Demo cafe restock: bottled drinks and coffee beans.",
            packages=[
                Package(width=35, length=50, height=30, weight=Decimal("14.40"), stackable=True),
                Package(width=35, length=50, height=30, weight=Decimal("14.40"), stackable=True),
                Package(width=45, length=60, height=40, weight=Decimal("21.60"), stackable=True),
            ],
        ),
        Shipment(
            customer_id=by_name["Central Corner Shop"].id,
            delivery_date=today + timedelta(days=1),
            priority=ShipmentPriority.HIGH,
            status=ShipmentStatus.PENDING,
            notes="Demo appliance delivery: keep the large carton upright.",
            packages=[
                Package(width=55, length=70, height=50, weight=Decimal("28.00"), stackable=False),
                Package(width=40, length=55, height=35, weight=Decimal("12.50"), stackable=True),
                Package(width=35, length=45, height=30, weight=Decimal("8.75"), stackable=True),
            ],
        ),
        Shipment(
            customer_id=by_name["Riverside Cafe"].id,
            delivery_date=today + timedelta(days=2),
            priority=ShipmentPriority.NORMAL,
            status=ShipmentStatus.PENDING,
            notes="Demo cafe equipment: handle the grinder carton with care.",
            packages=[
                Package(width=40, length=60, height=40, weight=Decimal("24.00"), stackable=True),
                Package(width=45, length=65, height=45, weight=Decimal("19.50"), stackable=False),
                Package(width=30, length=40, height=25, weight=Decimal("6.80"), stackable=True),
            ],
        ),
        Shipment(
            customer_id=by_name["Central Corner Shop"].id,
            delivery_date=today + timedelta(days=2),
            priority=ShipmentPriority.LOW,
            status=ShipmentStatus.PENDING,
            notes="Demo promotion stock: bulky display cartons.",
            packages=[
                Package(width=50, length=75, height=40, weight=Decimal("16.25"), stackable=True),
                Package(width=45, length=70, height=35, weight=Decimal("14.50"), stackable=True),
                Package(width=60, length=80, height=55, weight=Decimal("32.00"), stackable=False),
            ],
        ),
    ]
    # Stable customer/notes pairs identify the sample batch even after dates or
    # statuses change in normal use. Locked customers serialize repeat seed runs.
    existing = set(
        session.execute(
            select(Shipment.customer_id, Shipment.notes).where(
                Shipment.customer_id.in_([customer.id for customer in customers]),
                Shipment.notes.in_([shipment.notes for shipment in shipments]),
            )
        ).all()
    )
    missing = [
        shipment for shipment in shipments if (shipment.customer_id, shipment.notes) not in existing
    ]
    session.add_all(missing)
    return bool(missing)


def main() -> None:
    inserted = seed_database()
    print("Seed data inserted." if inserted else "Seed data already exists; nothing changed.")


if __name__ == "__main__":
    main()
