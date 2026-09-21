from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, Enum, ForeignKey, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base

if TYPE_CHECKING:
    from app.customer.model import Customer
    from app.packing.model import PackagePlacement


class ShipmentPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class ShipmentStatus(StrEnum):
    PENDING = "pending"
    PLANNED = "planned"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class Shipment(Base):
    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    delivery_date: Mapped[date] = mapped_column(Date, index=True)
    priority: Mapped[ShipmentPriority] = mapped_column(
        Enum(
            ShipmentPriority,
            name="shipment_priority",
            native_enum=True,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=ShipmentPriority.NORMAL,
    )
    status: Mapped[ShipmentStatus] = mapped_column(
        Enum(
            ShipmentStatus,
            name="shipment_status",
            native_enum=True,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=ShipmentStatus.PENDING,
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(Text)

    customer: Mapped[Customer] = relationship(back_populates="shipments")
    packages: Mapped[list[Package]] = relationship(
        back_populates="shipment",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Package(Base):
    __tablename__ = "packages"

    id: Mapped[int] = mapped_column(primary_key=True)
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), index=True
    )
    width: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    length: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    height: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    weight: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    stackable: Mapped[bool] = mapped_column(Boolean, default=True)

    shipment: Mapped[Shipment] = relationship(back_populates="packages")
    loading_placements: Mapped[list[PackagePlacement]] = relationship(back_populates="package")
