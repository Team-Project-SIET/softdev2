from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base

if TYPE_CHECKING:
    from app.routing.model import Route
    from app.vehicle.model import Vehicle


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    phone: Mapped[str] = mapped_column(String(32))
    line_user_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    vehicle_id: Mapped[int | None] = mapped_column(
        ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True, index=True
    )

    vehicle: Mapped[Vehicle | None] = relationship(back_populates="drivers")
    routes: Mapped[list[Route]] = relationship(back_populates="driver")
