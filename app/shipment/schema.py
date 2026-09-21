from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.shipment.model import ShipmentPriority, ShipmentStatus


class PackageBase(BaseModel):
    width: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    length: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    height: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    weight: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    stackable: bool = True


class PackageCreate(PackageBase):
    pass


class PackageRead(PackageBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shipment_id: int


class ShipmentBase(BaseModel):
    customer_id: int = Field(gt=0)
    delivery_date: date
    priority: ShipmentPriority = ShipmentPriority.NORMAL
    status: ShipmentStatus = ShipmentStatus.PENDING
    notes: str | None = None


class ShipmentCreate(ShipmentBase):
    packages: list[PackageCreate] = Field(default_factory=list)


class ShipmentRead(ShipmentBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    packages: list[PackageRead] = Field(default_factory=list)


class ShipmentSummary(BaseModel):
    id: int
    customer_name: str
    delivery_date: date
    priority: ShipmentPriority
    status: ShipmentStatus
    package_count: int
    total_weight: Decimal
