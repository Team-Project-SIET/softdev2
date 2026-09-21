import io
from datetime import date
from decimal import Decimal
from urllib.error import HTTPError, URLError
from uuid import UUID

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.customer.model import Customer
from app.driver.model import Driver
from app.integrations.line.client import LINE_PUSH_URL, LineClient
from app.integrations.line.exceptions import (
    InvalidLineReceiverError,
    LineApiError,
    LineNetworkError,
    MissingLineUserIdError,
)
from app.integrations.line.schemas import LineRoutePlan
from app.integrations.line.service import LineService
from app.routing.model import Route, RouteStatus, RouteStop
from app.shipment.model import Package, Shipment, ShipmentPriority, ShipmentStatus
from app.vehicle.model import Vehicle, VehicleStatus

LINE_USER_ID = "U" + "b" * 32


class RecordingClient:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls: list[tuple[str, LineRoutePlan, UUID | None]] = []

    def send_route_plan(
        self, line_user_id: str, route_plan: LineRoutePlan, *, retry_key: UUID | None = None
    ) -> None:
        self.calls.append((line_user_id, route_plan, retry_key))
        if self.failure is not None:
            raise self.failure


def create_route(
    session_factory: sessionmaker[Session], *, line_user_id: str = LINE_USER_ID
) -> int:
    with session_factory.begin() as session:
        vehicle = Vehicle(
            name="LINE Van",
            width=180,
            length=300,
            height=180,
            max_weight=1000,
            status=VehicleStatus.AVAILABLE,
        )
        driver = Driver(
            name="LINE Driver",
            phone="0812345678",
            line_user_id=line_user_id,
            vehicle=vehicle,
        )
        customer = Customer(
            name="LINE Customer",
            phone="021234567",
            address="123 Delivery Road",
            latitude=Decimal("13.700001"),
            longitude=Decimal("100.500002"),
        )
        shipment = Shipment(
            customer=customer,
            delivery_date=date(2026, 9, 22),
            priority=ShipmentPriority.NORMAL,
            status=ShipmentStatus.PLANNED,
            notes=None,
            packages=[
                Package(width=10, length=20, height=30, weight=5, stackable=True),
                Package(width=15, length=25, height=35, weight=7, stackable=False),
            ],
        )
        session.add_all([vehicle, driver, customer, shipment])
        session.flush()
        route = Route(
            vehicle=vehicle,
            driver=driver,
            total_distance=Decimal("12.345"),
            total_weight=Decimal("12"),
            status=RouteStatus.PLANNED,
            stops=[
                RouteStop(stop_order=0, distance_from_previous=0, is_depot=True),
                RouteStop(
                    shipment=shipment,
                    customer=customer,
                    stop_order=1,
                    distance_from_previous=Decimal("6.1"),
                    is_depot=False,
                ),
                RouteStop(
                    stop_order=2,
                    distance_from_previous=Decimal("6.245"),
                    is_depot=True,
                ),
            ],
        )
        session.add(route)
        session.flush()
        return route.id


def test_service_loads_saved_route_and_sends_assigned_driver(
    session_factory: sessionmaker[Session],
) -> None:
    route_id = create_route(session_factory)
    client = RecordingClient()
    service = LineService(session_factory=session_factory, client=client)

    candidates = service.list_routes()
    sent = service.send_route_plan(route_id)

    assert candidates[0].driver_name == "LINE Driver"
    assert candidates[0].has_line_user_id
    assert sent.route_id == route_id
    assert sent.driver_name == "LINE Driver"
    assert len(client.calls) == 1
    receiver, plan, retry_key = client.calls[0]
    assert receiver == LINE_USER_ID
    assert retry_key is not None and retry_key.version == 4
    assert plan.vehicle_name == "LINE Van"
    assert plan.stops[0].customer_name == "LINE Customer"
    assert len(plan.stops[0].package_ids) == 2


def test_service_rejects_driver_without_line_user_id(
    session_factory: sessionmaker[Session],
) -> None:
    route_id = create_route(session_factory, line_user_id="")
    client = RecordingClient()

    with pytest.raises(MissingLineUserIdError, match="has no LINE user ID"):
        LineService(session_factory=session_factory, client=client).send_route_plan(route_id)

    assert not client.calls


def test_service_propagates_line_api_failure(
    session_factory: sessionmaker[Session],
) -> None:
    route_id = create_route(session_factory)
    client = RecordingClient(LineApiError("LINE API returned HTTP 500", status_code=500))

    with pytest.raises(LineApiError, match="HTTP 500"):
        LineService(session_factory=session_factory, client=client).send_route_plan(route_id)


def test_retry_uses_same_intent_and_new_send_uses_new_key(
    session_factory: sessionmaker[Session],
) -> None:
    route_id = create_route(session_factory)
    client = RecordingClient()
    service = LineService(session_factory=session_factory, client=client)
    intent = service.prepare_send_intent(route_id)

    service.send_intent(intent)
    with session_factory.begin() as session:
        route = session.get(Route, route_id)
        route.total_distance = Decimal("99")
        route.driver.line_user_id = "U" + "c" * 32
    service.send_intent(intent)
    service.send_route_plan(route_id)

    assert client.calls[0] == client.calls[1]
    assert client.calls[2][2] != intent.retry_key
    assert client.calls[2][0] != intent.line_user_id


def test_invalid_seed_style_line_id_is_not_ready(
    session_factory: sessionmaker[Session],
) -> None:
    route_id = create_route(session_factory, line_user_id="seed-driver-anan")
    service = LineService(session_factory=session_factory, client=RecordingClient())

    assert not service.list_routes()[0].has_line_user_id
    with pytest.raises(InvalidLineReceiverError, match="invalid LINE user ID"):
        service.prepare_send_intent(route_id)


def test_timeout_then_accepted_retry_preserves_http_body_and_key(
    session_factory: sessionmaker[Session],
) -> None:
    route_id = create_route(session_factory)
    requests = []

    def http_open(request: object, *, timeout: float) -> object:
        requests.append(request)
        if len(requests) == 1:
            raise URLError("response timed out")
        raise HTTPError(
            LINE_PUSH_URL,
            409,
            "Conflict",
            {"x-line-accepted-request-id": "accepted-request"},
            io.BytesIO(b'{"message":"The retry key is already accepted"}'),
        )

    service = LineService(
        session_factory=session_factory,
        client=LineClient("mock-token", http_open=http_open),
    )
    intent = service.prepare_send_intent(route_id)
    with pytest.raises(LineNetworkError, match="timed out"):
        service.send_intent(intent)
    with session_factory.begin() as session:
        route = session.get(Route, route_id)
        route.total_distance = Decimal("99")
        route.driver.line_user_id = "U" + "c" * 32
    assert service.send_intent(intent).route_id == route_id

    first, second = requests
    assert first.data == second.data
    assert first.get_header("X-line-retry-key") == str(intent.retry_key)
    assert second.get_header("X-line-retry-key") == str(intent.retry_key)
    assert b'"to": "Ubbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"' in second.data
