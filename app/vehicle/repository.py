from sqlalchemy import select
from sqlalchemy.orm import Session

from app.vehicle.model import Vehicle


class VehicleRepository:
    def list_all(self, session: Session) -> list[Vehicle]:
        statement = select(Vehicle).order_by(Vehicle.name)
        return list(session.scalars(statement).all())
