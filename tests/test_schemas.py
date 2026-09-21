from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.customer.schema import CustomerCreate
from app.shipment.schema import PackageCreate, ShipmentCreate


def test_customer_coordinates_are_validated() -> None:
    with pytest.raises(ValidationError):
        CustomerCreate(
            name="Outside Earth",
            phone="000",
            address="Unknown",
            latitude=Decimal("91"),
            longitude=Decimal("100"),
        )


def test_shipment_create_accepts_nested_packages() -> None:
    shipment = ShipmentCreate(
        customer_id=1,
        delivery_date=date(2026, 1, 1),
        packages=[PackageCreate(width=10, length=20, height=30, weight=4.5, stackable=True)],
    )

    assert shipment.packages[0].weight == Decimal("4.5")


def test_package_dimensions_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        PackageCreate(width=0, length=20, height=30, weight=4.5)
