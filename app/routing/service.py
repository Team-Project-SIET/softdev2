from collections.abc import Callable, Sequence
from concurrent.futures import CancelledError
from decimal import Decimal
from threading import Event

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.session import create_session
from app.routing.optimizer import CVRPOptimizer
from app.routing.repository import DriverAssignmentChangedError, RoutingRepository
from app.routing.schemas import (
    Coordinates,
    RoutingCandidates,
    RoutingPlan,
    RoutingProblem,
    RoutingShipment,
    RoutingVehicle,
    SavedRoutingPlan,
    ShipmentCandidate,
    VehicleCandidate,
)
from app.shipment.model import Package, Shipment, ShipmentStatus
from app.vehicle.model import Vehicle, VehicleStatus


class StaleRoutingPlanError(ValueError):
    """The saved preview no longer matches eligible routing inputs."""


class InvalidRoutingPlanError(ValueError):
    """A typed route plan violates the depot or assignment contract."""


class RoutingService:
    """Coordinates database reads, optimizer input preparation, and persistence."""

    def __init__(
        self,
        session_factory: Callable[[], Session] = create_session,
        repository: RoutingRepository | None = None,
        optimizer: CVRPOptimizer | None = None,
        depot: Coordinates | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.repository = repository or RoutingRepository()
        self.optimizer = optimizer or CVRPOptimizer()
        self.depot = depot

    def list_candidates(self) -> RoutingCandidates:
        with self.session_factory() as session:
            shipments = self.repository.list_pending_shipments(session)
            vehicles = self.repository.list_available_vehicles(session)
            return RoutingCandidates(
                shipments=[
                    ShipmentCandidate(
                        id=shipment.id,
                        customer_name=shipment.customer.name,
                        delivery_date=shipment.delivery_date,
                        demand_kg=self._shipment_demand(shipment.packages),
                    )
                    for shipment in shipments
                ],
                vehicles=[
                    VehicleCandidate(
                        id=vehicle.id,
                        name=vehicle.name,
                        capacity_kg=vehicle.max_weight,
                    )
                    for vehicle in vehicles
                ],
            )

    def optimize(
        self,
        shipment_ids: Sequence[int],
        vehicle_ids: Sequence[int],
        *,
        cancel_event: Event | None = None,
    ) -> RoutingPlan:
        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError("route optimization was replaced")
        if not shipment_ids:
            raise ValueError("select at least one pending shipment")
        if not vehicle_ids:
            raise ValueError("select at least one available vehicle")
        if len(vehicle_ids) > 3:
            raise ValueError("select no more than three vehicles")

        requested_shipments = set(shipment_ids)
        requested_vehicles = set(vehicle_ids)
        with self.session_factory() as session:
            shipments = self.repository.list_pending_shipments(session, requested_shipments)
            vehicles = self.repository.list_available_vehicles(session, requested_vehicles)
            found_shipments = {shipment.id for shipment in shipments}
            found_vehicles = {vehicle.id for vehicle in vehicles}
            if found_shipments != requested_shipments:
                missing = sorted(requested_shipments - found_shipments)
                raise ValueError(f"shipments are missing or no longer pending: {missing}")
            if found_vehicles != requested_vehicles:
                missing = sorted(requested_vehicles - found_vehicles)
                raise ValueError(f"vehicles are missing or unavailable: {missing}")

            problem = RoutingProblem(
                depot=self._depot_coordinates(),
                shipments=[
                    RoutingShipment(
                        shipment_id=shipment.id,
                        customer_id=shipment.customer_id,
                        location=Coordinates(
                            latitude=float(shipment.customer.latitude),
                            longitude=float(shipment.customer.longitude),
                        ),
                        demand_kg=self._shipment_demand(shipment.packages),
                    )
                    for shipment in shipments
                ],
                vehicles=[
                    RoutingVehicle(
                        vehicle_id=vehicle.id,
                        capacity_kg=vehicle.max_weight,
                    )
                    for vehicle in vehicles
                ],
            )

        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError("route optimization was replaced")
        return self.optimizer.optimize(problem, cancel_event=cancel_event)

    def save_plan(self, plan: RoutingPlan) -> SavedRoutingPlan:
        # model_copy(update=...) bypasses Pydantic validation, so validate the
        # complete typed preview again at the persistence boundary.
        try:
            plan = RoutingPlan.model_validate(plan.model_dump())
        except ValidationError as exc:
            raise InvalidRoutingPlanError(f"invalid route preview: {exc}") from exc
        source = self._validate_plan(plan)
        shipment_ids = {shipment.shipment_id for shipment in source.shipments}
        vehicle_ids = {vehicle.vehicle_id for vehicle in source.vehicles}
        with self.session_factory() as session, session.begin():
            shipments, vehicles = self.repository.lock_plan_sources(
                session, shipment_ids, vehicle_ids
            )
            self._validate_current_sources(source, shipments, vehicles)
            existing = self.repository.active_shipment_ids(session, shipment_ids)
            if existing:
                raise StaleRoutingPlanError(
                    f"shipments already have active routes: {sorted(existing)}; optimize again"
                )
            claimed = self.repository.claim_pending_shipments(session, shipment_ids)
            if claimed != shipment_ids:
                raise StaleRoutingPlanError("shipments changed while saving; optimize again")
            try:
                routes = self.repository.save_plan(session, plan)
            except DriverAssignmentChangedError as exc:
                raise StaleRoutingPlanError(f"{exc}; optimize again") from exc
            route_ids = [route.id for route in routes]
        shipment_count = sum(
            1 for route in plan.routes for stop in route.stops if not stop.is_depot
        )
        return SavedRoutingPlan(route_ids=route_ids, shipment_count=shipment_count)

    @staticmethod
    def _validate_plan(plan: RoutingPlan) -> RoutingProblem:
        source = plan.source_problem
        if source is None:
            raise InvalidRoutingPlanError("route preview has no source snapshot; optimize again")
        if plan.depot != source.depot:
            raise InvalidRoutingPlanError("route depot differs from its source snapshot")

        vehicles = {vehicle.vehicle_id: vehicle for vehicle in source.vehicles}
        shipments = {shipment.shipment_id: shipment for shipment in source.shipments}
        route_vehicle_ids = [route.vehicle_id for route in plan.routes]
        if len(route_vehicle_ids) != len(set(route_vehicle_ids)) or set(route_vehicle_ids) != set(
            vehicles
        ):
            raise InvalidRoutingPlanError("route vehicles differ from the source snapshot")

        assigned: list[int] = []
        for route in plan.routes:
            stops = route.stops
            if (
                not stops[0].is_depot
                or not stops[-1].is_depot
                or stops[0].distance_from_previous != 0
                or any(stop.is_depot for stop in stops[1:-1])
                or [stop.stop_order for stop in stops] != list(range(len(stops)))
            ):
                raise InvalidRoutingPlanError("each route must run from depot to depot in order")
            if sum((stop.distance_from_previous for stop in stops), Decimal(0)) != (
                route.total_distance
            ):
                raise InvalidRoutingPlanError("route distance does not match its stops")
            delivery_ids = [stop.shipment_id for stop in stops[1:-1]]
            if any(shipment_id not in shipments for shipment_id in delivery_ids):
                raise InvalidRoutingPlanError("route references a shipment outside its source")
            if any(
                stop.customer_id != shipments[stop.shipment_id].customer_id for stop in stops[1:-1]
            ):
                raise InvalidRoutingPlanError("route stop customer does not match shipment")
            weight = sum(
                (shipments[shipment_id].demand_kg for shipment_id in delivery_ids), Decimal(0)
            )
            if weight != route.total_weight or weight > vehicles[route.vehicle_id].capacity_kg:
                raise InvalidRoutingPlanError("route payload differs from the source snapshot")
            assigned.extend(delivery_ids)

        if len(assigned) != len(set(assigned)) or set(assigned) != set(shipments):
            raise InvalidRoutingPlanError("each source shipment must occur in exactly one route")
        if sum((route.total_distance for route in plan.routes), Decimal(0)) != (
            plan.total_distance
        ):
            raise InvalidRoutingPlanError("fleet distance does not match its routes")
        return source

    def _validate_current_sources(
        self, source: RoutingProblem, shipments: list[Shipment], vehicles: list[Vehicle]
    ) -> None:
        expected_shipments = {shipment.shipment_id: shipment for shipment in source.shipments}
        expected_vehicles = {vehicle.vehicle_id: vehicle for vehicle in source.vehicles}
        if {shipment.id for shipment in shipments} != set(expected_shipments):
            raise StaleRoutingPlanError("selected shipments are missing; optimize again")
        if {vehicle.id for vehicle in vehicles} != set(expected_vehicles):
            raise StaleRoutingPlanError("selected vehicles are missing; optimize again")
        if self._depot_coordinates() != source.depot:
            raise StaleRoutingPlanError("depot changed; optimize again")

        for shipment in shipments:
            original = expected_shipments[shipment.id]
            if shipment.status != ShipmentStatus.PENDING:
                raise StaleRoutingPlanError(
                    f"shipment #{shipment.id} is no longer pending; optimize again"
                )
            if shipment.customer is None or (
                shipment.customer_id != original.customer_id
                or Coordinates(
                    latitude=float(shipment.customer.latitude),
                    longitude=float(shipment.customer.longitude),
                )
                != original.location
                or self._shipment_demand(shipment.packages) != original.demand_kg
            ):
                raise StaleRoutingPlanError(
                    f"shipment #{shipment.id} routing inputs changed; optimize again"
                )
        for vehicle in vehicles:
            original = expected_vehicles[vehicle.id]
            if vehicle.status != VehicleStatus.AVAILABLE:
                raise StaleRoutingPlanError(
                    f"vehicle #{vehicle.id} is no longer available; optimize again"
                )
            if vehicle.max_weight != original.capacity_kg:
                raise StaleRoutingPlanError(
                    f"vehicle #{vehicle.id} capacity changed; optimize again"
                )

    def _depot_coordinates(self) -> Coordinates:
        if self.depot is not None:
            return self.depot
        settings = get_settings()
        return Coordinates(
            latitude=settings.depot_latitude,
            longitude=settings.depot_longitude,
        )

    @staticmethod
    def _shipment_demand(packages: Sequence[Package]) -> Decimal:
        return sum(
            (package.weight for package in packages),
            start=Decimal("0"),
        )
