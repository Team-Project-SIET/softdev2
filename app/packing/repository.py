from sqlalchemy import Select, select
from sqlalchemy.orm import Session, selectinload

from app.packing.model import LoadingPlan, PackagePlacement
from app.packing.schemas import LoadingPlanDraft
from app.routing.model import Route, RouteStop
from app.shipment.model import Package, Shipment
from app.vehicle.model import Vehicle


class PackingRepository:
    @staticmethod
    def _route_query() -> Select[tuple[Route]]:
        return select(Route).options(
            selectinload(Route.vehicle),
            selectinload(Route.stops)
            .selectinload(RouteStop.shipment)
            .selectinload(Shipment.packages),
        )

    def list_routes(self, session: Session) -> list[Route]:
        return list(session.scalars(self._route_query().order_by(Route.id.desc())).all())

    def get_route(self, session: Session, route_id: int) -> Route:
        route = session.scalar(self._route_query().where(Route.id == route_id))
        if route is None:
            raise ValueError(f"saved route #{route_id} does not exist")
        return route

    def lock_route_sources(self, session: Session, route_id: int) -> Route:
        """Hold all loading inputs stable through comparison and insertion."""

        route = session.scalar(select(Route).where(Route.id == route_id).with_for_update())
        if route is None:
            raise ValueError(f"saved route #{route_id} does not exist")
        session.scalar(select(Vehicle).where(Vehicle.id == route.vehicle_id).with_for_update())
        stops = list(
            session.scalars(
                select(RouteStop)
                .where(RouteStop.route_id == route_id)
                .order_by(RouteStop.id)
                .with_for_update()
            ).all()
        )
        shipment_ids = {stop.shipment_id for stop in stops if stop.shipment_id is not None}
        list(
            session.scalars(
                select(Shipment)
                .where(Shipment.id.in_(shipment_ids))
                .order_by(Shipment.id)
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
        return self.get_route(session, route_id)

    def save_plan(self, session: Session, draft: LoadingPlanDraft) -> LoadingPlan:
        result = draft.result
        plan = LoadingPlan(
            route_id=draft.route_id,
            vehicle_id=result.vehicle_id,
            total_package_volume=result.total_package_volume,
            used_cargo_volume=result.used_cargo_volume,
            cargo_volume=result.cargo_volume,
            volume_utilization_percentage=result.volume_utilization_percentage,
            total_loaded_weight=result.total_loaded_weight,
            payload_utilization_percentage=result.payload_utilization_percentage,
            status=result.status,
            unplaced_packages=[p.model_dump(mode="json") for p in result.unplaced_packages],
            source_snapshot=draft.problem.model_dump(mode="json"),
            placements=[
                PackagePlacement(**p.model_dump(exclude={"vehicle_id"})) for p in result.placements
            ],
        )
        session.add(plan)
        session.flush()
        return plan
