from collections.abc import Callable
from decimal import Decimal

from sqlalchemy.orm import Session

from app.database.session import create_session
from app.shipment.repository import ShipmentRepository
from app.shipment.schema import ShipmentSummary


class ShipmentService:
    def __init__(
        self,
        session_factory: Callable[[], Session] = create_session,
        repository: ShipmentRepository | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.repository = repository or ShipmentRepository()

    def list_shipments(self) -> list[ShipmentSummary]:
        with self.session_factory() as session:
            shipments = self.repository.list_all(session)
            return [
                ShipmentSummary(
                    id=shipment.id,
                    customer_name=shipment.customer.name,
                    delivery_date=shipment.delivery_date,
                    priority=shipment.priority,
                    status=shipment.status,
                    package_count=len(shipment.packages),
                    total_weight=sum(
                        (package.weight for package in shipment.packages), start=Decimal("0")
                    ),
                )
                for shipment in shipments
            ]
