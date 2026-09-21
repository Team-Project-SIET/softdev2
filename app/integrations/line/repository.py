from sqlalchemy import Select, select
from sqlalchemy.orm import Session, selectinload

from app.routing.model import Route, RouteStop
from app.shipment.model import Shipment


class LineRepository:
    """Read saved routes with all data required by a LINE route message."""

    @staticmethod
    def _route_query() -> Select[tuple[Route]]:
        return select(Route).options(
            selectinload(Route.driver),
            selectinload(Route.vehicle),
            selectinload(Route.stops).selectinload(RouteStop.customer),
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
