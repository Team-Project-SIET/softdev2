from collections.abc import Callable
from concurrent.futures import CancelledError
from threading import Event

from sqlalchemy.orm import Session

from app.database.session import create_session
from app.packing.optimizer import PackingOptimizer
from app.packing.repository import PackingRepository
from app.packing.schemas import (
    DeliveryStop,
    LoadingPlanDraft,
    PackingPackage,
    PackingProblem,
    PackingVehicle,
    SavedLoadingPlan,
    SavedRouteCandidate,
)
from app.routing.model import Route


class PackingService:
    """Translate a saved vehicle route into pure optimizer input and save accepted plans."""

    def __init__(
        self,
        session_factory: Callable[[], Session] = create_session,
        repository: PackingRepository | None = None,
        optimizer: PackingOptimizer | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.repository = repository or PackingRepository()
        self.optimizer = optimizer or PackingOptimizer()

    def list_routes(self) -> list[SavedRouteCandidate]:
        with self.session_factory() as session:
            return [
                SavedRouteCandidate(
                    route_id=route.id,
                    vehicle_id=route.vehicle_id,
                    vehicle_name=route.vehicle.name,
                    stop_count=sum(not stop.is_depot for stop in route.stops),
                    package_count=sum(
                        len(stop.shipment.packages)
                        for stop in route.stops
                        if not stop.is_depot and stop.shipment is not None
                    ),
                )
                for route in self.repository.list_routes(session)
            ]

    def optimize(self, route_id: int, *, cancel_event: Event | None = None) -> LoadingPlanDraft:
        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError("loading optimization was replaced")
        with self.session_factory() as session:
            problem = self._problem(self.repository.get_route(session, route_id))
        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError("loading optimization was replaced")
        return LoadingPlanDraft(
            route_id=route_id,
            problem=problem,
            result=self.optimizer.solve(
                problem.vehicle,
                problem.packages,
                problem.delivery_sequence,
                cancel_event=cancel_event,
            ),
        )

    def save_plan(self, draft: LoadingPlanDraft) -> SavedLoadingPlan:
        with self.session_factory() as session, session.begin():
            problem = self._problem(self.repository.lock_route_sources(session, draft.route_id))
            if problem != draft.problem:
                raise ValueError(
                    "route, vehicle or packages changed; run loading optimization again"
                )
            expected = self.optimizer.solve(
                problem.vehicle, problem.packages, problem.delivery_sequence
            )
            if draft.result != expected:
                raise ValueError("loading result changed; run loading optimization again")
            plan = self.repository.save_plan(session, draft)
            return SavedLoadingPlan(
                loading_plan_id=plan.id,
                route_id=plan.route_id,
                placement_count=len(plan.placements),
                status=plan.status,
            )

    @staticmethod
    def _problem(route: Route) -> PackingProblem:
        vehicle = route.vehicle
        sequence: list[DeliveryStop] = []
        packages: list[PackingPackage] = []
        for stop in sorted(route.stops, key=lambda stop: stop.stop_order):
            if stop.is_depot:
                continue
            shipment = stop.shipment
            if shipment is None:
                raise ValueError(f"route stop {stop.stop_order} has no shipment")
            sequence.append(DeliveryStop(shipment_id=shipment.id, stop_order=stop.stop_order))
            packages.extend(
                PackingPackage(
                    package_id=package.id,
                    shipment_id=shipment.id,
                    width=package.width,
                    length=package.length,
                    height=package.height,
                    weight=package.weight,
                    stackable=package.stackable,
                )
                for package in sorted(shipment.packages, key=lambda package: package.id)
            )
        return PackingProblem(
            vehicle=PackingVehicle(
                vehicle_id=vehicle.id,
                width=vehicle.width,
                length=vehicle.length,
                height=vehicle.height,
                max_weight=vehicle.max_weight,
            ),
            packages=packages,
            delivery_sequence=sequence,
        )
