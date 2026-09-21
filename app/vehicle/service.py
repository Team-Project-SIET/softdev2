from collections.abc import Callable

from sqlalchemy.orm import Session

from app.database.session import create_session
from app.vehicle.repository import VehicleRepository
from app.vehicle.schema import VehicleRead


class VehicleService:
    def __init__(
        self,
        session_factory: Callable[[], Session] = create_session,
        repository: VehicleRepository | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.repository = repository or VehicleRepository()

    def list_vehicles(self) -> list[VehicleRead]:
        with self.session_factory() as session:
            vehicles = self.repository.list_all(session)
            return [VehicleRead.model_validate(vehicle) for vehicle in vehicles]
