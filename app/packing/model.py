from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.packing.schemas import LoadingStatus

if TYPE_CHECKING:
    from app.routing.model import Route
    from app.shipment.model import Package
    from app.vehicle.model import Vehicle


class LoadingPlan(Base):
    __tablename__ = "loading_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id", ondelete="CASCADE"), index=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    total_package_volume: Mapped[Decimal] = mapped_column(Numeric(38, 6))
    used_cargo_volume: Mapped[Decimal] = mapped_column(Numeric(38, 6))
    cargo_volume: Mapped[Decimal] = mapped_column(Numeric(38, 6))
    volume_utilization_percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    total_loaded_weight: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    payload_utilization_percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    status: Mapped[LoadingStatus] = mapped_column(
        Enum(
            LoadingStatus,
            name="loading_status",
            values_callable=lambda enum: [item.value for item in enum],
        ),
        index=True,
    )
    # Preserve partial results and source dimensions even if operational data changes.
    unplaced_packages: Mapped[list[dict]] = mapped_column(JSON)
    source_snapshot: Mapped[dict] = mapped_column(JSON)

    route: Mapped[Route] = relationship(back_populates="loading_plans")
    vehicle: Mapped[Vehicle] = relationship(back_populates="loading_plans")
    placements: Mapped[list[PackagePlacement]] = relationship(
        back_populates="loading_plan",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="PackagePlacement.unloading_order",
    )


class PackagePlacement(Base):
    __tablename__ = "package_placements"
    __table_args__ = (
        UniqueConstraint("loading_plan_id", "package_id", name="uq_placements_plan_package"),
        UniqueConstraint("loading_plan_id", "loading_order", name="uq_placements_plan_loading"),
        UniqueConstraint("loading_plan_id", "unloading_order", name="uq_placements_plan_unloading"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    loading_plan_id: Mapped[int] = mapped_column(
        ForeignKey("loading_plans.id", ondelete="CASCADE"), index=True
    )
    package_id: Mapped[int] = mapped_column(ForeignKey("packages.id"), index=True)
    x: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    y: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    z: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    orientation: Mapped[str] = mapped_column(String(3))
    width: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    length: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    height: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    loading_order: Mapped[int]
    unloading_order: Mapped[int]
    stop_order: Mapped[int]

    loading_plan: Mapped[LoadingPlan] = relationship(back_populates="placements")
    package: Mapped[Package] = relationship(back_populates="loading_placements")
