from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base

if TYPE_CHECKING:
    from app.customer.model import Customer
    from app.driver.model import Driver
    from app.packing.model import LoadingPlan
    from app.shipment.model import Shipment
    from app.vehicle.model import Vehicle


class RouteStatus(StrEnum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), index=True)
    driver_id: Mapped[int | None] = mapped_column(
        ForeignKey("drivers.id", ondelete="SET NULL"), index=True
    )
    total_distance: Mapped[Decimal] = mapped_column(Numeric(12, 3), comment="Kilometers")
    total_weight: Mapped[Decimal] = mapped_column(Numeric(12, 3), comment="Kilograms")
    status: Mapped[RouteStatus] = mapped_column(
        Enum(
            RouteStatus,
            name="route_status",
            native_enum=True,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=RouteStatus.PLANNED,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    vehicle: Mapped[Vehicle] = relationship(back_populates="routes")
    driver: Mapped[Driver | None] = relationship(back_populates="routes")
    loading_plans: Mapped[list[LoadingPlan]] = relationship(
        back_populates="route", cascade="all, delete-orphan", passive_deletes=True
    )
    stops: Mapped[list[RouteStop]] = relationship(
        back_populates="route",
        cascade="all, delete-orphan",
        order_by="RouteStop.stop_order",
    )


class RouteStop(Base):
    __tablename__ = "route_stops"
    __table_args__ = (
        UniqueConstraint("route_id", "stop_order", name="uq_route_stops_route_order"),
        UniqueConstraint("route_id", "shipment_id", name="uq_route_stops_route_shipment"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id", ondelete="CASCADE"), index=True)
    shipment_id: Mapped[int | None] = mapped_column(ForeignKey("shipments.id"), index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)
    stop_order: Mapped[int]
    distance_from_previous: Mapped[Decimal] = mapped_column(Numeric(12, 3), comment="Kilometers")
    is_depot: Mapped[bool] = mapped_column(Boolean, default=False)

    route: Mapped[Route] = relationship(back_populates="stops")
    shipment: Mapped[Shipment | None] = relationship()
    customer: Mapped[Customer | None] = relationship()
