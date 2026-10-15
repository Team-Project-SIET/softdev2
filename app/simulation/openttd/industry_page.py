"""Bounded read-only transport DTOs; no planning or prepared-world contracts."""

import hashlib
from dataclasses import asdict, dataclass

from app.simulation.openttd.observation_protocol import (
    BridgeProtocolError,
    MalformedMessage,
    _object,
    _serialize,
    validate_request_id,
)
from app.simulation.openttd.world_info import WorldInfoResponse

# 15.3 IndustryID pool has 64000 slots; industry types are 0..239.
MAX_INDUSTRY_ID = 63999
MAX_PAGE_SIZE = 5  # 192 envelope + 62 bytes/record: 502 <= 512; six need 564.


def _integer(value: object, maximum: int, label: str) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise MalformedMessage(f"invalid {label}")
    return value


def _cursor(value: object) -> int | None:
    return None if value is None else _integer(value, MAX_INDUSTRY_ID, "cursor")


@dataclass(frozen=True)
class IndustryPageRequest:
    request_id: str
    after_id: int | None = None
    limit: int = MAX_PAGE_SIZE

    def __post_init__(self) -> None:
        validate_request_id(self.request_id)
        _cursor(self.after_id)
        if _integer(self.limit, MAX_PAGE_SIZE, "limit") == 0:
            raise MalformedMessage("limit must be positive")

    def to_bytes(self) -> bytes:
        return _serialize(dict(protocol=1, type="industry_page", **asdict(self)))

    @classmethod
    def parse(cls, payload: bytes) -> IndustryPageRequest:
        obj = _object(
            payload, "industry_page", {"protocol", "type", "request_id", "after_id", "limit"}
        )
        return cls(
            validate_request_id(obj["request_id"]),
            _cursor(obj["after_id"]),
            _integer(obj["limit"], MAX_PAGE_SIZE, "limit"),
        )


@dataclass(frozen=True)
class IndustryRecord:
    id: int
    type: int
    tile: int
    x: int
    y: int

    def __post_init__(self) -> None:
        _integer(self.id, MAX_INDUSTRY_ID, "industry ID")
        _integer(self.type, 239, "industry type")
        _integer(self.tile, 2**32 - 2, "tile")
        _integer(self.x, 65535, "x")
        _integer(self.y, 65535, "y")

    def validate_location(self, world: WorldInfoResponse) -> None:
        if self.x >= world.map_width or self.y >= world.map_height:
            raise MalformedMessage("industry coordinates outside known map")
        if self.tile != self.y * world.map_width + self.x:
            raise MalformedMessage("inconsistent industry tile/x/y")


@dataclass(frozen=True)
class IndustryPageResponse:
    request_id: str
    industries: tuple[IndustryRecord, ...]
    next_after_id: int | None
    has_more: bool

    def __post_init__(self) -> None:
        validate_request_id(self.request_id)
        _cursor(self.next_after_id)
        if type(self.has_more) is not bool or type(self.industries) is not tuple:
            raise MalformedMessage("invalid page types")
        if len(self.industries) > MAX_PAGE_SIZE or any(
            not isinstance(record, IndustryRecord) for record in self.industries
        ):
            raise MalformedMessage("invalid industry records")
        ids = [record.id for record in self.industries]
        if any(a >= b for a, b in zip(ids, ids[1:])):
            raise MalformedMessage("industry IDs must be strictly ascending")
        if self.has_more:
            if not ids or self.next_after_id != ids[-1]:
                raise MalformedMessage("has_more requires records and last-ID cursor")
        elif self.next_after_id is not None:
            raise MalformedMessage("final page must have null cursor")

    def to_bytes(self) -> bytes:
        return _serialize(
            dict(protocol=1, type="industry_page_result", status="ok", **asdict(self))
        )

    @classmethod
    def parse(cls, payload: bytes) -> IndustryPageResponse:
        obj = _object(
            payload,
            "industry_page_result",
            {"protocol", "type", "request_id", "status", "industries", "next_after_id", "has_more"},
        )
        if obj["status"] != "ok":
            raise BridgeProtocolError("unsupported industry page status")
        raw = obj["industries"]
        if not isinstance(raw, list):
            raise MalformedMessage("industries must be an array")
        records = []
        for item in raw:
            if not isinstance(item, dict) or set(item) != {"id", "type", "tile", "x", "y"}:
                raise MalformedMessage("invalid industry record fields")
            records.append(
                IndustryRecord(
                    *(
                        _integer(item[k], maximum, k)
                        for k, maximum in (
                            ("id", MAX_INDUSTRY_ID),
                            ("type", 239),
                            ("tile", 2**32 - 2),
                            ("x", 65535),
                            ("y", 65535),
                        )
                    )
                )
            )
        if type(obj["has_more"]) is not bool:
            raise MalformedMessage("has_more must be boolean")
        return cls(
            validate_request_id(obj["request_id"]),
            tuple(records),
            _cursor(obj["next_after_id"]),
            obj["has_more"],
        )

    def validate_page(self, request: IndustryPageRequest, world: WorldInfoResponse) -> None:
        if self.request_id != request.request_id:
            raise BridgeProtocolError("industry page request_id mismatch")
        if len(self.industries) > request.limit or (
            self.has_more and len(self.industries) != request.limit
        ):
            raise MalformedMessage("incomplete intermediate or oversized page")
        for record in self.industries:
            if request.after_id is not None and record.id <= request.after_id:
                raise MalformedMessage("industry ID does not advance cursor")
            record.validate_location(world)


PAGE_NETWORK_SEQUENCE = (
    "INDUSTRY_PAGE_REQUEST_SENT",
    "INDUSTRY_PAGE_RESPONSE_RECEIVED",
    "TRANSPORT_RECEIPT_CREATED",
    "PAGE_VALIDATED",
)


@dataclass(frozen=True)
class IndustryPageReceipt:
    request_id: str
    request_payload_sha256: str
    response_payload_sha256: str

    @classmethod
    def correlate(cls, request: bytes, response: bytes) -> IndustryPageReceipt:
        query = IndustryPageRequest.parse(request)
        result = IndustryPageResponse.parse(response)
        if query.request_id != result.request_id:
            raise BridgeProtocolError("industry page request_id mismatch")
        return cls(
            query.request_id,
            hashlib.sha256(request).hexdigest(),
            hashlib.sha256(response).hexdigest(),
        )


@dataclass(frozen=True)
class IndustryPageExchange:
    request_payload: bytes
    response_payload: bytes
    receipt: IndustryPageReceipt
    ordered_sequence: tuple[str, ...]
    requests_sent: int = 1
    matching_responses: int = 1
    retries: int = 0
    protocol_operations: int = 4

    @property
    def response(self) -> IndustryPageResponse:
        return IndustryPageResponse.parse(self.response_payload)

    def validate(self, world: WorldInfoResponse) -> None:
        if type(self.protocol_operations) is not int or self.protocol_operations < 4:
            raise BridgeProtocolError("invalid industry page protocol operation count")
        if self.ordered_sequence != PAGE_NETWORK_SEQUENCE or (
            self.requests_sent,
            self.matching_responses,
            self.retries,
        ) != (1, 1, 0):
            raise BridgeProtocolError("incomplete industry page network evidence")
        if self.receipt != IndustryPageReceipt.correlate(
            self.request_payload, self.response_payload
        ):
            raise BridgeProtocolError("industry page receipt mismatch")
        self.response.validate_page(IndustryPageRequest.parse(self.request_payload), world)
