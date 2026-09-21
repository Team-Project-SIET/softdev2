from collections.abc import Collection

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.customer.model import Customer
from app.driver.model import Driver
from app.routing.model import Route, RouteStatus, RouteStop
from app.routing.schemas import RoutingPlan
from app.shipment.model import Package, Shipment, ShipmentStatus
from app.vehicle.model import Vehicle, VehicleStatus


class DriverAssignmentChangedError(ValueError):
    """A driver moved while the route-save transaction was selecting it."""


class RoutingRepository:
    def lock_plan_sources(
        self, session: Session, shipment_ids: set[int], vehicle_ids: set[int]
    ) -> tuple[list[Shipment], list[Vehicle]]:
        """Lock optimization inputs in a stable order until the save commits."""

        vehicles = list(
            session.scalars(
                select(Vehicle)
                .where(Vehicle.id.in_(vehicle_ids))
                .order_by(Vehicle.id)
                .with_for_update()
            ).all()
        )
        shipments = list(
            session.scalars(
                select(Shipment)
                .where(Shipment.id.in_(shipment_ids))
                .order_by(Shipment.id)
                .with_for_update()
            ).all()
        )
        customer_ids = {shipment.customer_id for shipment in shipments}
        list(
            session.scalars(
                select(Customer)
                .where(Customer.id.in_(customer_ids))
                .order_by(Customer.id)
                .with_for_update()
            ).all()
        )
        list(
            session.scalars(
                select(Package)
                .where(Package.shipment_id.in_(shipment_ids))
                .order_by(Package.id)
                .with_for_update()
            ).all()
        )
        return shipments, vehicles

    def claim_pending_shipments(self, session: Session, shipment_ids: set[int]) -> set[int]:
        """The status predicate is rechecked by PostgreSQL after a competing update."""

        return set(
            session.scalars(
                update(Shipment)
                .where(Shipment.id.in_(shipment_ids), Shipment.status == ShipmentStatus.PENDING)
                .values(status=ShipmentStatus.PLANNED)
                .returning(Shipment.id)
            ).all()
        )

    def active_shipment_ids(self, session: Session, shipment_ids: set[int]) -> set[int]:
        return set(
            session.scalars(
                select(RouteStop.shipment_id)
                .join(Route)
                .where(
                    RouteStop.shipment_id.in_(shipment_ids),
                    Route.status != RouteStatus.CANCELLED,
                )
            ).all()
        )

    def list_pending_shipments(
        self,
        session: Session,
        shipment_ids: Collection[int] | None = None,
    ) -> list[Shipment]:
        statement = (
            select(Shipment)
            .where(Shipment.status == ShipmentStatus.PENDING)
            .options(selectinload(Shipment.customer), selectinload(Shipment.packages))
            .order_by(Shipment.delivery_date, Shipment.id)
        )
        if shipment_ids is not None:
            statement = statement.where(Shipment.id.in_(shipment_ids))
        return list(session.scalars(statement).all())

    def list_available_vehicles(
        self,
        session: Session,
        vehicle_ids: Collection[int] | None = None,
    ) -> list[Vehicle]:
        statement = (
            select(Vehicle).where(Vehicle.status == VehicleStatus.AVAILABLE).order_by(Vehicle.name)
        )
        if vehicle_ids is not None:
            statement = statement.where(Vehicle.id.in_(vehicle_ids))
        return list(session.scalars(statement).all())

    def save_plan(self, session: Session, plan: RoutingPlan) -> list[Route]:
        routes: list[Route] = []
        for route_plan in plan.routes:
            route = Route(
                vehicle_id=route_plan.vehicle_id,
                driver_id=self._vehicle_driver_id(session, route_plan.vehicle_id),
                total_distance=route_plan.total_distance,
                total_weight=route_plan.total_weight,
                status=RouteStatus.PLANNED,
                stops=[
                    RouteStop(
                        shipment_id=stop.shipment_id,
                        customer_id=stop.customer_id,
                        stop_order=stop.stop_order,
                        distance_from_previous=stop.distance_from_previous,
                        is_depot=stop.is_depot,
                    )
                    for stop in route_plan.stops
                ],
            )
            session.add(route)
            routes.append(route)

        session.flush()
        return routes

    def _vehicle_driver_id(self, session: Session, vehicle_id: int) -> int | None:
        """Lock and recheck the selected driver until the route is committed."""

        driver_ids = self._candidate_driver_ids(session, vehicle_id)
        if not driver_ids:
            return None
        drivers = list(
            session.scalars(
                select(Driver)
                .where(Driver.id.in_(driver_ids))
                .order_by(Driver.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).all()
        )
        if [driver.id for driver in drivers] != driver_ids or any(
            driver.vehicle_id != vehicle_id for driver in drivers
        ):
            raise DriverAssignmentChangedError(
                f"driver assignment for vehicle #{vehicle_id} changed while saving"
            )
        return driver_ids[0] if len(driver_ids) == 1 else None

    @staticmethod
    def _candidate_driver_ids(session: Session, vehicle_id: int) -> list[int]:
        return list(
            session.scalars(
                select(Driver.id).where(Driver.vehicle_id == vehicle_id).order_by(Driver.id)
            ).all()
        )
