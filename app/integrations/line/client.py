import json
import re
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

from app.integrations.line.exceptions import (
    InvalidLineReceiverError,
    LineApiError,
    LineMessageTooLongError,
    LineNetworkError,
    MissingLineTokenError,
)
from app.integrations.line.schemas import LineRoutePlan

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
LINE_USER_ID_PATTERN = re.compile(r"U[0-9a-f]{32}")
MAX_TEXT_LENGTH = 5000


def valid_line_user_id(value: str | None) -> bool:
    return bool(value and LINE_USER_ID_PATTERN.fullmatch(value.strip()))


def _coordinate(value: Any) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def format_route_plan(route_plan: LineRoutePlan) -> str:
    """Format a saved route as the first plain-text LINE message."""

    lines = [
        "ROUTE PLAN",
        f"Route ID: {route_plan.route_id}",
        f"Driver: {route_plan.driver_name}",
        f"Vehicle: {route_plan.vehicle_name}",
        f"Total stops: {len(route_plan.stops)}",
        f"Total distance: {route_plan.total_distance:.3f} km",
    ]
    for stop in sorted(route_plan.stops, key=lambda item: item.stop_number):
        lines.extend(
            [
                "",
                f"Stop {stop.stop_number}",
                f"Customer: {stop.customer_name}",
                f"Address: {stop.address}",
                "Package IDs: " + ", ".join(str(package_id) for package_id in stop.package_ids),
            ]
        )
        if stop.latitude is not None and stop.longitude is not None:
            latitude = _coordinate(stop.latitude)
            longitude = _coordinate(stop.longitude)
            lines.extend(
                [
                    f"Coordinates: {latitude}, {longitude}",
                    "Navigate: "
                    f"https://www.google.com/maps/dir/?api=1&destination={latitude},{longitude}",
                ]
            )
    return "\n".join(lines)


class LineClient:
    """Minimal client for LINE Messaging API push messages."""

    def __init__(
        self,
        channel_access_token: str | None,
        *,
        timeout_seconds: float = 10,
        http_open: Callable[..., Any] | None = None,
    ) -> None:
        self.channel_access_token = channel_access_token
        self.timeout_seconds = timeout_seconds
        self.http_open = http_open or urlopen

    def send_route_plan(
        self, line_user_id: str, route_plan: LineRoutePlan, *, retry_key: UUID | None = None
    ) -> None:
        token = (self.channel_access_token or "").strip()
        if not token:
            raise MissingLineTokenError(
                "LINE_CHANNEL_ACCESS_TOKEN is not configured; add it to the environment"
            )
        receiver = line_user_id.strip()
        if not valid_line_user_id(receiver):
            raise InvalidLineReceiverError(
                "LINE receiver is invalid; expected a user ID beginning with U followed by "
                "32 lowercase hexadecimal characters"
            )

        message = format_route_plan(route_plan)
        if len(message) > MAX_TEXT_LENGTH:
            raise LineMessageTooLongError(
                f"route message is {len(message)} characters; LINE allows {MAX_TEXT_LENGTH}"
            )
        body = json.dumps(
            {
                "to": receiver,
                "messages": [{"type": "text", "text": message}],
            }
        ).encode("utf-8")
        request = Request(
            LINE_PUSH_URL,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-Line-Retry-Key": str(retry_key or uuid4()),
            },
        )
        try:
            with self.http_open(request, timeout=self.timeout_seconds) as response:
                status_code = response.getcode()
                if not 200 <= status_code < 300:
                    if self._already_accepted(status_code, getattr(response, "headers", {})):
                        return
                    response_body = response.read()
                    self._raise_api_error(status_code, response_body)
        except HTTPError as exc:
            if self._already_accepted(exc.code, exc.headers or {}):
                return
            self._raise_api_error(exc.code, exc.read())
        except (URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise LineNetworkError(f"could not reach LINE Messaging API: {reason}") from exc

    @staticmethod
    def _already_accepted(status_code: int, headers: Any) -> bool:
        return status_code == 409 and bool(
            headers.get("x-line-accepted-request-id") or headers.get("X-Line-Accepted-Request-Id")
        )

    @staticmethod
    def _raise_api_error(status_code: int, response_body: bytes) -> None:
        detail = "unknown error"
        try:
            payload = json.loads(response_body.decode("utf-8"))
            if isinstance(payload, dict):
                detail = str(payload.get("message") or detail)
        except UnicodeDecodeError, json.JSONDecodeError:
            pass
        if status_code == 400:
            raise InvalidLineReceiverError(f"LINE rejected the receiver or message: {detail}")
        raise LineApiError(
            f"LINE API returned HTTP {status_code}: {detail}", status_code=status_code
        )
