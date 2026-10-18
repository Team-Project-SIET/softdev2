"""Pure compact terrain wire values; diagnostic rows project into existing TileFact."""

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from app.simulation.openttd.observation_protocol import (
    BridgeProtocolError,
    _object,
    _serialize,
    validate_request_id,
)
from app.simulation.openttd.supplemental_planning_facts import Region, TileFact

PAGE_SIZE = 5
MAX_REQUEST_BYTES = 159
MAX_RESPONSE_BYTES = 508
TILE_NETWORK_SEQUENCE = (
    "TILE_FACTS_REQUEST_SENT",
    "TILE_FACTS_RESPONSE_RECEIVED",
    "TRANSPORT_RECEIPT_CREATED",
    "TILE_FACTS_VALIDATED",
)
FLAG_NAMES = (
    "buildable",
    "water",
    "coast",
    "tree",
    "farm",
    "rock",
    "rough",
    "road",
    "rail",
    "water_transport",
    "air_transport",
    "house",
    "station",
)


class TileFailure(StrEnum):
    INVALID_REGION = "INVALID_REGION"
    INVALID_TILE = "INVALID_TILE"
    UNSUPPORTED_NATIVE_FACT = "UNSUPPORTED_NATIVE_FACT"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    REQUEST_ID_MISMATCH = "REQUEST_ID_MISMATCH"
    CURSOR_MISMATCH = "CURSOR_MISMATCH"
    DUPLICATE_TILE = "DUPLICATE_TILE"
    MISSING_TILE = "MISSING_TILE"
    INCOMPLETE_SWEEP = "INCOMPLETE_SWEEP"
    COVERAGE_LIMIT_EXCEEDED = "COVERAGE_LIMIT_EXCEEDED"
    RESPONSE_LIMIT_EXCEEDED = "RESPONSE_LIMIT_EXCEEDED"
    ACCOUNTING_LIMIT_EXCEEDED = "ACCOUNTING_LIMIT_EXCEEDED"
    PROVENANCE_MISMATCH = "PROVENANCE_MISMATCH"
    ECONOMY_MONTH_CROSSING = "ECONOMY_MONTH_CROSSING"
    SWEEP_DRIFT = "SWEEP_DRIFT"
    CONNECTION_REPLACED = "CONNECTION_REPLACED"
    BRIDGE_FAILURE = "BRIDGE_FAILURE"
    UNSUPPORTED_PROTOCOL = "UNSUPPORTED_PROTOCOL"
    UNSUPPORTED_ROAD_TYPE = "UNSUPPORTED_ROAD_TYPE"
    REQUEST_LIMIT_EXCEEDED = "REQUEST_LIMIT_EXCEEDED"
    # Additive schema-2 codes: historical identities are unchanged.
    UNSUPPORTED_CLASSIFICATION_SCHEMA = "UNSUPPORTED_CLASSIFICATION_SCHEMA"
    CLASSIFICATION_UNAVAILABLE = "CLASSIFICATION_UNAVAILABLE"


class TileQueryError(BridgeProtocolError):
    """Existing protocol failure family, with a bounded command-specific code."""

    def __init__(self, code: TileFailure):
        self.code = code
        super().__init__(code.value)


def integer(value: object, low: int, high: int, code=TileFailure.MALFORMED_RESPONSE) -> int:
    if type(value) is not int or not low <= value <= high:
        raise TileQueryError(code)
    return value


def rectangle(value: object) -> Region:
    if not isinstance(value, list) or len(value) != 4:
        raise TileQueryError(TileFailure.INVALID_REGION)
    x, y, w, h = (integer(v, 0, 4095, TileFailure.INVALID_REGION) for v in value)
    if not w or not h or w * h > 256:
        raise TileQueryError(TileFailure.COVERAGE_LIMIT_EXCEEDED)
    return Region(x=x, y=y, width=w, height=h)


def selector(r: Region) -> list[int]:
    return [r.x, r.y, r.width, r.height]


@dataclass(frozen=True)
class TileFactsRequest:
    request_id: str
    region: Region
    cursor: int

    def __post_init__(self):
        validate_request_id(self.request_id)
        if not isinstance(self.region, Region):
            raise TileQueryError(TileFailure.INVALID_REGION)
        rectangle(selector(self.region))
        integer(
            self.cursor, 0, self.region.width * self.region.height - 1, TileFailure.CURSOR_MISMATCH
        )
        if self.cursor % PAGE_SIZE:
            raise TileQueryError(TileFailure.CURSOR_MISMATCH)

    def to_bytes(self) -> bytes:
        result = _serialize(
            dict(
                protocol=1,
                type="tile_facts_page",
                request_id=self.request_id,
                region=selector(self.region),
                cursor=self.cursor,
            )
        )
        if len(result) > MAX_REQUEST_BYTES:
            raise TileQueryError(TileFailure.REQUEST_LIMIT_EXCEEDED)
        return result

    @classmethod
    def parse(cls, payload: bytes):
        if len(payload) > MAX_REQUEST_BYTES:
            raise TileQueryError(TileFailure.REQUEST_LIMIT_EXCEEDED)
        o = _object(
            payload, "tile_facts_page", {"protocol", "type", "request_id", "region", "cursor"}
        )
        return cls(
            validate_request_id(o["request_id"]),
            rectangle(o["region"]),
            integer(o["cursor"], 0, 255),
        )

    def require_map(self, width: int, height: int):
        for n in (width, height):
            integer(n, 1, 4096)
            if n & (n - 1):
                raise TileQueryError(TileFailure.INVALID_REGION)
        if self.region.x + self.region.width > width or self.region.y + self.region.height > height:
            raise TileQueryError(TileFailure.INVALID_REGION)


@dataclass(frozen=True)
class TileFactsResponse:
    request_id: str
    region: Region
    cursor: int
    map_width: int
    map_height: int
    date_before: int
    date_after: int
    rows: tuple[tuple[int | None, ...], ...]
    next_cursor: int | None
    has_more: bool

    def __post_init__(self):
        q = TileFactsRequest(self.request_id, self.region, self.cursor)
        q.require_map(self.map_width, self.map_height)
        integer(self.date_before, 0, 2147483647)
        integer(self.date_after, self.date_before, 2147483647)
        if type(self.has_more) is not bool or not isinstance(self.rows, tuple):
            raise TileQueryError(TileFailure.MALFORMED_RESPONSE)
        total = self.region.width * self.region.height
        count = min(PAGE_SIZE, total - self.cursor)
        if len(self.rows) != count:
            raise TileQueryError(TileFailure.MISSING_TILE)
        more = self.cursor + count < total
        if self.has_more != more or self.next_cursor != (self.cursor + count if more else None):
            raise TileQueryError(TileFailure.CURSOR_MISMATCH)
        if more:
            integer(self.next_cursor, 1, 255, TileFailure.CURSOR_MISMATCH)
        ids = []
        for offset, row in enumerate(self.rows):
            if not isinstance(row, tuple) or len(row) != 10:
                raise TileQueryError(TileFailure.MALFORMED_RESPONSE)
            limits = (
                (0, 16777215),
                (0, 255),
                (0, 31),
                (0, 8191),
                (0, 63999),
                (-1, 14),
                (0, 1),
                (0, 15),
                (0, 15),
                (0, 15),
            )
            for i, (lo, hi) in enumerate(limits):
                if i == 4 and row[i] is None:
                    continue
                integer(row[i], lo, hi)
            tile = integer(row[0], 0, 16777215)
            if tile in ids:
                raise TileQueryError(TileFailure.DUPLICATE_TILE)
            ids.append(tile)
            ordinal = self.cursor + offset
            x = self.region.x + ordinal % self.region.width
            y = self.region.y + ordinal // self.region.width
            if tile != y * self.map_width + x:
                raise TileQueryError(TileFailure.INVALID_TILE)
            assessed = 0
            for bit, (dx, dy) in enumerate(((0, -1), (1, 0), (0, 1), (-1, 0))):
                if (
                    self.region.x <= x + dx < self.region.x + self.region.width
                    and self.region.y <= y + dy < self.region.y + self.region.height
                ):
                    assessed |= 1 << bit
            out = integer(row[7], 0, 15)
            incoming = integer(row[8], 0, 15)
            if (
                row[9] != assessed
                or (out | incoming) & ~assessed
                or ((out | incoming) and not row[6])
            ):
                raise TileQueryError(TileFailure.UNSUPPORTED_NATIVE_FACT)
            flags = integer(row[3], 0, 8191)
            if row[6] and not flags & 128:
                raise TileQueryError(TileFailure.UNSUPPORTED_NATIVE_FACT)
            # TileFact has no house/station fields: preserve these diagnostic flags and
            # conservatively prevent their projection from becoming vacant/buildable.
            self.tile_fact(row)

    def tile_fact(self, row: tuple[int | None, ...]) -> TileFact:
        tile = integer(row[0], 0, 16777215)
        flags = integer(row[3], 0, 8191)
        values = {name: bool(flags & (1 << i)) for i, name in enumerate(FLAG_NAMES[:11])}
        if flags & ((1 << 11) | (1 << 12)):
            values["buildable"] = False
        return TileFact(
            tile_id=tile,
            x=tile % self.map_width,
            y=tile // self.map_width,
            min_height=integer(row[1], 0, 255),
            slope=integer(row[2], 0, 31),
            industry_id=row[4],
            **values,
        )

    @property
    def tiles(self) -> tuple[TileFact, ...]:
        return tuple(self.tile_fact(row) for row in self.rows)

    def to_bytes(self):
        return _serialize(
            dict(
                protocol=1,
                type="tile_facts_page_result",
                status="ok",
                request_id=self.request_id,
                region=selector(self.region),
                cursor=self.cursor,
                map=[self.map_width, self.map_height],
                date_before=self.date_before,
                date_after=self.date_after,
                tiles=[list(r) for r in self.rows],
                next_cursor=self.next_cursor,
                has_more=self.has_more,
            )
        )

    @classmethod
    def parse(cls, payload: bytes):
        if len(payload) > MAX_RESPONSE_BYTES:
            raise TileQueryError(TileFailure.RESPONSE_LIMIT_EXCEEDED)
        # Error messages use a distinct strict bounded envelope.
        try:
            raw = json.loads(payload)
        except (ValueError, UnicodeError, RecursionError) as e:
            raise TileQueryError(TileFailure.MALFORMED_RESPONSE) from e
        if isinstance(raw, dict) and raw.get("status") == "error":
            o = _object(
                payload,
                "tile_facts_page_result",
                {"protocol", "type", "request_id", "status", "error_code", "cursor", "failed_tile"},
            )
            for key, maximum in (("cursor", 255), ("failed_tile", 16777215)):
                if o[key] is not None:
                    integer(o[key], 0, maximum)
            try:
                code = TileFailure(o["error_code"])
            except (ValueError, TypeError) as e:
                raise TileQueryError(TileFailure.MALFORMED_RESPONSE) from e
            raise TileQueryError(code)
        o = _object(
            payload,
            "tile_facts_page_result",
            {
                "protocol",
                "type",
                "status",
                "request_id",
                "region",
                "cursor",
                "map",
                "date_before",
                "date_after",
                "tiles",
                "next_cursor",
                "has_more",
            },
        )
        if (
            o["status"] != "ok"
            or not isinstance(o["map"], list)
            or len(o["map"]) != 2
            or not isinstance(o["tiles"], list)
            or any(not isinstance(r, list) for r in o["tiles"])
        ):
            raise TileQueryError(TileFailure.MALFORMED_RESPONSE)
        if type(o["has_more"]) is not bool:
            raise TileQueryError(TileFailure.MALFORMED_RESPONSE)
        next_cursor = None if o["next_cursor"] is None else integer(o["next_cursor"], 1, 255)
        return cls(
            validate_request_id(o["request_id"]),
            rectangle(o["region"]),
            integer(o["cursor"], 0, 255),
            integer(o["map"][0], 1, 4096),
            integer(o["map"][1], 1, 4096),
            integer(o["date_before"], 0, 2147483647),
            integer(o["date_after"], 0, 2147483647),
            tuple(tuple(r) for r in o["tiles"]),
            next_cursor,
            o["has_more"],
        )


@dataclass(frozen=True)
class TileFactsReceipt:
    request_id: str
    request_payload_sha256: str
    response_payload_sha256: str

    @classmethod
    def correlate(cls, request: bytes, response: bytes):
        q = TileFactsRequest.parse(request)
        if len(response) > MAX_RESPONSE_BYTES:
            raise TileQueryError(TileFailure.RESPONSE_LIMIT_EXCEEDED)
        # Correlation must precede propagating a bounded native error.
        try:
            identity = json.loads(response).get("request_id")
        except (ValueError, AttributeError) as e:
            raise TileQueryError(TileFailure.MALFORMED_RESPONSE) from e
        if identity != q.request_id:
            raise TileQueryError(TileFailure.REQUEST_ID_MISMATCH)
        r = TileFactsResponse.parse(response)
        if (r.region, r.cursor) != (q.region, q.cursor):
            raise TileQueryError(TileFailure.CURSOR_MISMATCH)
        return cls(
            q.request_id, hashlib.sha256(request).hexdigest(), hashlib.sha256(response).hexdigest()
        )


@dataclass(frozen=True)
class TileFactsExchange:
    request_payload: bytes
    response_payload: bytes
    receipt: TileFactsReceipt
    ordered_sequence: tuple[str, ...] = TILE_NETWORK_SEQUENCE
    protocol_operations: int = 4
    requests_sent: int = 1
    matching_responses: int = 1
    retries: int = 0

    @property
    def response(self):
        return TileFactsResponse.parse(self.response_payload)

    def validate(self):
        if (
            self.ordered_sequence != TILE_NETWORK_SEQUENCE
            or (self.requests_sent, self.matching_responses, self.retries) != (1, 1, 0)
            or type(self.protocol_operations) is not int
            or not 4 <= self.protocol_operations <= 8
            or self.receipt
            != TileFactsReceipt.correlate(self.request_payload, self.response_payload)
        ):
            raise TileQueryError(TileFailure.ACCOUNTING_LIMIT_EXCEEDED)
