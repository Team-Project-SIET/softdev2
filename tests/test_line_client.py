import io
import json
from decimal import Decimal
from urllib.error import HTTPError, URLError
from uuid import UUID, uuid4

import pytest

from app.integrations.line.client import LINE_PUSH_URL, LineClient, format_route_plan
from app.integrations.line.exceptions import (
    InvalidLineReceiverError,
    LineApiError,
    LineNetworkError,
    MissingLineTokenError,
)
from app.integrations.line.schemas import LineRoutePlan, LineRouteStop

LINE_USER_ID = "U" + "a" * 32


class FakeResponse:
    def __init__(
        self, status_code: int = 200, body: bytes = b"{}", headers: dict | None = None
    ) -> None:
        self.status_code = status_code
        self.body = body
        self.headers = headers or {}

    def getcode(self) -> int:
        return self.status_code

    def read(self) -> bytes:
        return self.body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        pass


def route_plan() -> LineRoutePlan:
    return LineRoutePlan(
        route_id=42,
        driver_name="Anan Chaiyasit",
        vehicle_name="Van 01",
        total_distance=Decimal("18.275"),
        stops=[
            LineRouteStop(
                stop_number=2,
                customer_name="Riverside Cafe",
                address="21 Charoen Krung Road",
                package_ids=[203],
                latitude=None,
                longitude=None,
            ),
            LineRouteStop(
                stop_number=1,
                customer_name="Central Corner Shop",
                address="99 Sukhumvit Road",
                package_ids=[101, 102],
                latitude=Decimal("13.736717"),
                longitude=Decimal("100.523186"),
            ),
        ],
    )


def test_route_message_contains_summary_and_ordered_delivery_stops() -> None:
    message = format_route_plan(route_plan())

    assert "Route ID: 42" in message
    assert "Driver: Anan Chaiyasit" in message
    assert "Vehicle: Van 01" in message
    assert "Total stops: 2" in message
    assert "Total distance: 18.275 km" in message
    assert message.index("Stop 1") < message.index("Stop 2")
    assert "Customer: Central Corner Shop" in message
    assert "Address: 99 Sukhumvit Road" in message
    assert "Package IDs: 101, 102" in message
    assert "Coordinates: 13.736717, 100.523186" in message
    assert "https://www.google.com/maps/dir/?api=1&destination=13.736717,100.523186" in message
    assert message.count("Navigate:") == 1


def test_send_route_plan_posts_plain_text_push_message() -> None:
    requests: list[tuple[object, float]] = []

    def http_open(request: object, *, timeout: float) -> FakeResponse:
        requests.append((request, timeout))
        return FakeResponse()

    LineClient("secret-token", timeout_seconds=3, http_open=http_open).send_route_plan(
        LINE_USER_ID, route_plan()
    )

    assert len(requests) == 1
    request, timeout = requests[0]
    assert request.full_url == LINE_PUSH_URL  # type: ignore[attr-defined]
    assert request.get_method() == "POST"  # type: ignore[attr-defined]
    assert request.get_header("Authorization") == "Bearer secret-token"  # type: ignore[attr-defined]
    assert request.get_header("Content-type") == "application/json"  # type: ignore[attr-defined]
    assert UUID(request.get_header("X-line-retry-key")).version == 4  # type: ignore[attr-defined]
    assert timeout == 3
    payload = json.loads(request.data)  # type: ignore[attr-defined]
    assert payload == {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": format_route_plan(route_plan())}],
    }


def test_missing_token_does_not_make_http_request() -> None:
    called = False

    def http_open(*args: object, **kwargs: object) -> FakeResponse:
        nonlocal called
        called = True
        return FakeResponse()

    with pytest.raises(MissingLineTokenError, match="LINE_CHANNEL_ACCESS_TOKEN"):
        LineClient(None, http_open=http_open).send_route_plan(LINE_USER_ID, route_plan())

    assert not called


def test_invalid_receiver_does_not_make_http_request() -> None:
    called = False

    def http_open(*args: object, **kwargs: object) -> FakeResponse:
        nonlocal called
        called = True
        return FakeResponse()

    with pytest.raises(InvalidLineReceiverError, match="receiver is invalid"):
        LineClient("token", http_open=http_open).send_route_plan("not-a-line-user-id", route_plan())

    assert not called


def test_line_api_failure_includes_status_and_safe_message() -> None:
    def http_open(*args: object, **kwargs: object) -> FakeResponse:
        raise HTTPError(
            LINE_PUSH_URL,
            401,
            "Unauthorized",
            {},
            io.BytesIO(b'{"message":"Authentication failed"}'),
        )

    with pytest.raises(LineApiError, match="HTTP 401: Authentication failed") as exc_info:
        LineClient("bad-token", http_open=http_open).send_route_plan(LINE_USER_ID, route_plan())

    assert exc_info.value.status_code == 401


def test_line_network_failure_is_translated() -> None:
    def http_open(*args: object, **kwargs: object) -> FakeResponse:
        raise URLError("temporary DNS failure")

    with pytest.raises(LineNetworkError, match="temporary DNS failure"):
        LineClient("token", http_open=http_open).send_route_plan(LINE_USER_ID, route_plan())


def test_explicit_retry_key_is_sent_unchanged() -> None:
    requests = []
    key = uuid4()

    def http_open(request: object, *, timeout: float) -> FakeResponse:
        requests.append(request)
        return FakeResponse()

    client = LineClient("token", http_open=http_open)
    client.send_route_plan(LINE_USER_ID, route_plan(), retry_key=key)
    client.send_route_plan(LINE_USER_ID, route_plan(), retry_key=key)

    assert [request.get_header("X-line-retry-key") for request in requests] == [str(key)] * 2
    assert requests[0].data == requests[1].data


def test_retried_already_accepted_push_is_successful() -> None:
    def http_open(*args: object, **kwargs: object) -> FakeResponse:
        raise HTTPError(
            LINE_PUSH_URL,
            409,
            "Conflict",
            {"x-line-accepted-request-id": "accepted-request"},
            io.BytesIO(b'{"message":"The retry key is already accepted"}'),
        )

    LineClient("token", http_open=http_open).send_route_plan(
        LINE_USER_ID, route_plan(), retry_key=uuid4()
    )
