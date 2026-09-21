from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LineRouteStop(BaseModel):
    model_config = ConfigDict(frozen=True)

    stop_number: int = Field(gt=0)
    customer_name: str
    address: str
    package_ids: tuple[int, ...]
    latitude: Decimal | None = None
    longitude: Decimal | None = None


class LineRoutePlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    route_id: int = Field(gt=0)
    driver_name: str
    vehicle_name: str
    total_distance: Decimal = Field(ge=0)
    stops: tuple[LineRouteStop, ...]


class LineRouteCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    route_id: int
    vehicle_name: str
    driver_name: str | None
    stop_count: int
    has_line_user_id: bool


class SentLineRoute(BaseModel):
    model_config = ConfigDict(frozen=True)

    route_id: int
    driver_name: str


class LineSendIntent(BaseModel):
    """One immutable recipient and payload, reused for an ambiguous retry."""

    model_config = ConfigDict(frozen=True)

    route_id: int = Field(gt=0)
    line_user_id: str
    route_plan: LineRoutePlan
    retry_key: UUID
