from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Enum, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base

if TYPE_CHECKING:
    from app.driver.model import Driver
    from app.packing.model import LoadingPlan
    from app.routing.model import Route


class VehicleStatus(StrEnum):
    AVAILABLE = "available"
    IN_USE = "in_use"
    MAINTENANCE = "maintenance"
    INACTIVE = "inactive"


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    width: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    length: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    height: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    max_weight: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[VehicleStatus] = mapped_column(
        Enum(
            VehicleStatus,
            name="vehicle_status",
            native_enum=True,
            values_callable=lambda enum: [item.value for item in enum],
        ),
        default=VehicleStatus.AVAILABLE,
        index=True,
    )

    drivers: Mapped[list[Driver]] = relationship(back_populates="vehicle")
    routes: Mapped[list[Route]] = relationship(back_populates="vehicle")
    loading_plans: Mapped[list[LoadingPlan]] = relationship(back_populates="vehicle")
