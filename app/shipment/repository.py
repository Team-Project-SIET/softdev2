from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.shipment.model import Shipment


class ShipmentRepository:
    def list_all(self, session: Session) -> list[Shipment]:
        statement = (
            select(Shipment)
            .options(selectinload(Shipment.customer), selectinload(Shipment.packages))
            .order_by(Shipment.delivery_date, Shipment.id)
        )
        return list(session.scalars(statement).all())
