from collections.abc import Callable
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.session import create_session
from app.integrations.line.client import LineClient, valid_line_user_id
from app.integrations.line.exceptions import (
    InvalidLineReceiverError,
    MissingLineUserIdError,
    RouteDriverNotAssignedError,
)
from app.integrations.line.repository import LineRepository
from app.integrations.line.schemas import (
    LineRouteCandidate,
    LineRoutePlan,
    LineRouteStop,
    LineSendIntent,
    SentLineRoute,
)
from app.routing.model import Route


class RoutePlanSender(Protocol):
    def send_route_plan(
        self, line_user_id: str, route_plan: LineRoutePlan, *, retry_key: UUID | None = None
    ) -> None: ...


class LineService:
    """Load saved route data and send it to the route's assigned driver."""

    def __init__(
        self,
        session_factory: Callable[[], Session] = create_session,
        repository: LineRepository | None = None,
        client: RoutePlanSender | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.repository = repository or LineRepository()
        self.client = client

    def list_routes(self) -> list[LineRouteCandidate]:
        with self.session_factory() as session:
            return [
                LineRouteCandidate(
                    route_id=route.id,
                    vehicle_name=route.vehicle.name,
                    driver_name=route.driver.name if route.driver else None,
                    stop_count=sum(not stop.is_depot for stop in route.stops),
                    has_line_user_id=bool(
                        route.driver and valid_line_user_id(route.driver.line_user_id)
                    ),
                )
                for route in self.repository.list_routes(session)
            ]

    def prepare_send_intent(self, route_id: int) -> LineSendIntent:
        with self.session_factory() as session:
            route = self.repository.get_route(session, route_id)
            if route.driver is None:
                raise RouteDriverNotAssignedError(f"route #{route_id} has no assigned driver")
            line_user_id = (route.driver.line_user_id or "").strip()
            if not line_user_id:
                raise MissingLineUserIdError(f"driver {route.driver.name} has no LINE user ID")
            if not valid_line_user_id(line_user_id):
                raise InvalidLineReceiverError(
                    f"driver {route.driver.name} has an invalid LINE user ID"
                )
            route_plan = self._route_plan(route)
        return LineSendIntent(
            route_id=route_id,
            line_user_id=line_user_id,
            route_plan=route_plan,
            retry_key=uuid4(),
        )

    def send_intent(self, intent: LineSendIntent) -> SentLineRoute:
        self._client().send_route_plan(
            intent.line_user_id, intent.route_plan, retry_key=intent.retry_key
        )
        return SentLineRoute(
            route_id=intent.route_plan.route_id, driver_name=intent.route_plan.driver_name
        )

    def send_route_plan(self, route_id: int) -> SentLineRoute:
        """A direct call starts a new send intent. Retrying uses send_intent."""

        return self.send_intent(self.prepare_send_intent(route_id))

    def _client(self) -> RoutePlanSender:
        if self.client is not None:
            return self.client
        settings = get_settings()
        self.client = LineClient(settings.line_channel_access_token)
        return self.client

    @staticmethod
    def _route_plan(route: Route) -> LineRoutePlan:
        if route.driver is None:
            raise RouteDriverNotAssignedError(f"route #{route.id} has no assigned driver")
        stops: list[LineRouteStop] = []
        for stop in sorted(route.stops, key=lambda item: item.stop_order):
            if stop.is_depot:
                continue
            if stop.customer is None or stop.shipment is None:
                raise ValueError(f"route #{route.id} stop {stop.stop_order} is incomplete")
            customer = stop.customer
            stops.append(
                LineRouteStop(
                    stop_number=stop.stop_order,
                    customer_name=customer.name,
                    address=customer.address,
                    package_ids=sorted(package.id for package in stop.shipment.packages),
                    latitude=customer.latitude,
                    longitude=customer.longitude,
                )
            )
        return LineRoutePlan(
            route_id=route.id,
            driver_name=route.driver.name,
            vehicle_name=route.vehicle.name,
            total_distance=route.total_distance,
            stops=stops,
        )
