"""Versioned native tile-classification observation: schema 2, additive only.

The frozen v1 ``tile_facts_page`` wire packs road-related predicates into one
bit and the :class:`TileFact` projection collapses the native house/station
bits into ``buildable=False``. That is sufficient for vacancy/admission, but it
loses the occupancy class for tiles that are neither buildable nor classified
ground (Seed 17 retains 19 such tiles; their concrete class is unrecoverable
offline and is never inferred from other fields).

Schema 2 adds a *separate* wire type — ``tile_classification_page`` — that
carries the full native predicate mask (15 bits, no packing loss), the valid
industry pointer and the native owner for each tile; the Python side derives a
single occupancy class by documented precedence. Historical protocol identity
is untouched: version 1 requests/responses, receipts, packet budgets, staged
compositions and retained evidence are unchanged. The new schema is versioned
explicitly (``schema=2`` inside a protocol-1 envelope), requires the composed
classification bridge (``terrain_classification_bridge``) and fails closed with
structured ``TileFailure`` codes when the wire or the data is unavailable —
missing classifications surface as ``TileClass.UNKNOWN_OCCUPANCY`` for facts
and ``TileFailure.CLASSIFICATION_UNAVAILABLE`` for absent evidence, never as
guesses from unrelated fields.

Row layout: ``[tile, elevation, slope, flags15, industry, owner]`` with the
industry sentinel ``null`` for no valid industry, mirroring schema 1 budgets
(PAGE_SIZE 5, request <= 159 bytes, response <= 508 bytes).
"""

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from app.simulation.openttd.observation_protocol import (
    _object,
    _serialize,
    validate_request_id,
)
from app.simulation.openttd.supplemental_planning_facts import (
    Region,
    SupplementalPlanningFacts,
    TileFact,
)
from app.simulation.openttd.tile_facts import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    PAGE_SIZE,
    TileFailure,
    TileQueryError,
    integer,
    rectangle,
    selector,
)

CLASSIFICATION_SCHEMA_VERSION = 2
REQUEST_TYPE = "tile_classification_page"
RESULT_TYPE = "tile_classification_page_result"

# Full native predicate mask (unlike schema 1 there is no road-predicate
# packing): schema-1 bits 0..6 and 10..12 keep their meaning; bits 7..9 split
# the packed road flag and shift the transport/occupancy bits. The layout is
# explicit here and mirrored byte-for-byte by the classification bridge.
CLASSIFICATION_FLAG_NAMES = (
    "buildable",
    "water",
    "coast",
    "tree",
    "farm",
    "rock",
    "rough",
    "road_tile",
    "road_track",
    "road_src_type",
    "rail",
    "water_transport",
    "airport",
    "house",
    "station",
)
FLAG_MASK_LIMIT = (1 << len(CLASSIFICATION_FLAG_NAMES)) - 1
ROW_WIDTH = 6
INDUSTRY_LIMIT = 63999


def flags_index(name: str) -> int:
    return CLASSIFICATION_FLAG_NAMES.index(name)


class TileClass(StrEnum):
    """Single-class native occupancy classification by documented precedence."""

    HOUSE = "HOUSE"
    STATION = "STATION"
    INDUSTRY = "INDUSTRY"
    WATER = "WATER"
    COAST = "COAST"
    AIRPORT = "AIRPORT"
    ROAD = "ROAD"
    RAIL = "RAIL"
    DOCK = "DOCK"
    TREES = "TREES"
    FARM = "FARM"
    ROCK = "ROCK"
    ROUGH = "ROUGH"
    CLEAR = "CLEAR"
    UNKNOWN_OCCUPANCY = "UNKNOWN_OCCUPANCY"


def classify_tile(flags: int, industry_id: int | None) -> TileClass:
    """Derive the occupancy class by precedence; never guesses.

    Precedence mirrors what the native predicates can establish about the tile:
    a house/station/industry/transport footprint is identified before any
    ground class. Co-occurring predicates keep the highest-precedence class. A
    tile with no identifying predicate that is also not buildable clear ground
    (e.g. an uncaptured obstruction type) reports UNKNOWN_OCCUPANCY.
    """
    if type(flags) is not int or not 0 <= flags <= FLAG_MASK_LIMIT:
        raise TileQueryError(TileFailure.MALFORMED_RESPONSE)
    if industry_id is not None and (
        type(industry_id) is not int or not 0 <= industry_id <= INDUSTRY_LIMIT
    ):
        raise TileQueryError(TileFailure.MALFORMED_RESPONSE)

    def flag(name: str) -> bool:
        return bool(flags & (1 << flags_index(name)))

    if flag("house"):
        return TileClass.HOUSE
    if flag("station"):
        return TileClass.STATION
    if industry_id is not None:
        return TileClass.INDUSTRY
    if flag("water"):
        return TileClass.WATER
    if flag("coast"):
        return TileClass.COAST
    if flag("airport"):
        return TileClass.AIRPORT
    if any(flag(n) for n in ("road_tile", "road_track", "road_src_type")):
        return TileClass.ROAD
    if flag("rail"):
        return TileClass.RAIL
    if flag("water_transport"):
        return TileClass.DOCK
    if flag("tree"):
        return TileClass.TREES
    if flag("farm"):
        return TileClass.FARM
    if flag("rock"):
        return TileClass.ROCK
    if flag("rough"):
        return TileClass.ROUGH
    if flag("buildable"):
        return TileClass.CLEAR
    return TileClass.UNKNOWN_OCCUPANCY


def classification_flags(tile_class: TileClass) -> int:
    """Reconstruct a minimal consistent flag mask for controlled fixtures.

    Production paths always use the native mask; this inverse exists only for
    generating positive/negative test rows (e.g. an UNKNOWN tile sets no bit).
    """
    name = {
        TileClass.HOUSE: "house",
        TileClass.STATION: "station",
        TileClass.WATER: "water",
        TileClass.COAST: "coast",
        TileClass.AIRPORT: "airport",
        TileClass.ROAD: "road_tile",
        TileClass.RAIL: "rail",
        TileClass.DOCK: "water_transport",
        TileClass.TREES: "tree",
        TileClass.FARM: "farm",
        TileClass.ROCK: "rock",
        TileClass.ROUGH: "rough",
        TileClass.CLEAR: "buildable",
    }.get(tile_class)
    return 0 if name is None else 1 << flags_index(name)


@dataclass(frozen=True)
class TileClassificationRequest:
    """Protocol-1 envelope with an explicit ``schema=2`` field; same guards."""

    request_id: str
    region: Region
    cursor: int
    schema: int = CLASSIFICATION_SCHEMA_VERSION

    def __post_init__(self):
        validate_request_id(self.request_id)
        if self.schema != CLASSIFICATION_SCHEMA_VERSION:
            raise TileQueryError(TileFailure.UNSUPPORTED_CLASSIFICATION_SCHEMA)
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
                type=REQUEST_TYPE,
                request_id=self.request_id,
                region=selector(self.region),
                cursor=self.cursor,
                schema=self.schema,
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
            payload,
            REQUEST_TYPE,
            {"protocol", "type", "request_id", "region", "cursor", "schema"},
        )
        return cls(
            validate_request_id(o["request_id"]),
            rectangle(o["region"]),
            integer(o["cursor"], 0, 255),
            integer(
                o["schema"],
                CLASSIFICATION_SCHEMA_VERSION,
                CLASSIFICATION_SCHEMA_VERSION,
                TileFailure.UNSUPPORTED_CLASSIFICATION_SCHEMA,
            ),
        )

    def require_map(self, width: int, height: int):
        for n in (width, height):
            integer(n, 1, 4096)
            if n & (n - 1):
                raise TileQueryError(TileFailure.INVALID_REGION)
        if self.region.x + self.region.width > width or self.region.y + self.region.height > height:
            raise TileQueryError(TileFailure.INVALID_REGION)


@dataclass(frozen=True)
class TileClassificationResponse:
    """Page of classification rows; completeness provenance mirrors schema 1."""

    request_id: str
    region: Region
    cursor: int
    schema: int
    map_width: int
    map_height: int
    date_before: int
    date_after: int
    rows: tuple[tuple[int | None, ...], ...]
    next_cursor: int | None
    has_more: bool

    def __post_init__(self):
        TileClassificationRequest(self.request_id, self.region, self.cursor, self.schema)
        TileClassificationRequest.require_map(self, self.map_width, self.map_height)
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
        ids: list[int] = []
        for offset, row in enumerate(self.rows):
            tile, _, _, _, _, _ = self._validated_row(row)
            x = self.region.x + (self.cursor + offset) % self.region.width
            y = self.region.y + (self.cursor + offset) // self.region.width
            if tile != y * self.map_width + x:
                raise TileQueryError(TileFailure.INVALID_TILE)
            if tile in ids:
                raise TileQueryError(TileFailure.DUPLICATE_TILE)
            ids.append(tile)

    def _validated_row(self, row: tuple[int | None, ...]) -> tuple[int, int, int, int, int, int]:
        if not isinstance(row, tuple) or len(row) != ROW_WIDTH:
            raise TileQueryError(TileFailure.MALFORMED_RESPONSE)
        limits = (
            (0, 16777215),
            (0, 255),
            (0, 31),
            (0, FLAG_MASK_LIMIT),
            (0, INDUSTRY_LIMIT),
            (-1, 14),
        )
        values: list[int] = []
        for value, (low, high) in zip(row, limits, strict=False):
            if value is None:
                if (low, high) != (0, INDUSTRY_LIMIT):
                    raise TileQueryError(TileFailure.UNSUPPORTED_NATIVE_FACT)
                values.append(-1)  # only the industry sentinel may be null
            elif type(value) is not int or not low <= value <= high:
                raise TileQueryError(TileFailure.UNSUPPORTED_NATIVE_FACT)
            else:
                values.append(value)
        return (values[0], values[1], values[2], values[3], values[4], values[5])

    @property
    def classification(self) -> tuple[tuple[int, TileClass, int | None, int], ...]:
        """(tile, class, industry|None, owner) per row in stable page order."""
        out: list[tuple[int, TileClass, int | None, int]] = []
        for row in self.rows:
            tile, elevation, slope, flags, industry, owner = self._validated_row(row)
            cls = classify_tile(flags, None if industry < 0 else industry)
            out.append((tile, cls, None if industry < 0 else industry, owner))
            del elevation, slope  # conveyed verbatim through the facts below
        return tuple(out)

    @property
    def geometry(self) -> dict[int, tuple[int, int, int]]:
        """tile -> (min_height/elevation, slope, flags) in page order."""
        return {
            tile: (elevation, slope, flags)
            for row in self.rows
            for tile, elevation, slope, flags, _, _ in [self._validated_row(row)]
        }

    def to_bytes(self) -> bytes:
        tiles: list[list[int | None]] = []
        for row in self.rows:
            tile, elevation, slope, flags, industry, owner = self._validated_row(row)
            tiles.append([tile, elevation, slope, flags, None if industry < 0 else industry, owner])
        result = _serialize(
            dict(
                protocol=1,
                type=RESULT_TYPE,
                schema=self.schema,
                request_id=self.request_id,
                status="ok",
                region=selector(self.region),
                cursor=self.cursor,
                map=[self.map_width, self.map_height],
                date_before=self.date_before,
                date_after=self.date_after,
                tiles=tiles,
                next_cursor=self.next_cursor,
                has_more=self.has_more,
            )
        )
        if len(result) > MAX_RESPONSE_BYTES:
            raise TileQueryError(TileFailure.RESPONSE_LIMIT_EXCEEDED)
        return result

    @classmethod
    def parse(cls, payload: bytes):
        if len(payload) > MAX_RESPONSE_BYTES:
            raise TileQueryError(TileFailure.RESPONSE_LIMIT_EXCEEDED)
        # Error envelopes use the v1 strict bounded shape plus schema=2.
        try:
            raw = json.loads(payload)
        except (ValueError, UnicodeError, RecursionError) as e:
            raise TileQueryError(TileFailure.MALFORMED_RESPONSE) from e
        if isinstance(raw, dict) and raw.get("status") == "error":
            o = _object(
                payload,
                RESULT_TYPE,
                {
                    "protocol",
                    "type",
                    "schema",
                    "request_id",
                    "status",
                    "error_code",
                    "cursor",
                    "failed_tile",
                },
            )
            schema = integer(
                o["schema"],
                CLASSIFICATION_SCHEMA_VERSION,
                CLASSIFICATION_SCHEMA_VERSION,
                TileFailure.UNSUPPORTED_CLASSIFICATION_SCHEMA,
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
            RESULT_TYPE,
            {
                "protocol",
                "type",
                "schema",
                "request_id",
                "status",
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
        if o["status"] != "ok":
            raise TileQueryError(TileFailure.BRIDGE_FAILURE)
        schema = integer(
            o["schema"],
            CLASSIFICATION_SCHEMA_VERSION,
            CLASSIFICATION_SCHEMA_VERSION,
            TileFailure.UNSUPPORTED_CLASSIFICATION_SCHEMA,
        )
        region = rectangle(o["region"])
        cursor = integer(o["cursor"], 0, 4095)
        o_map = o["map"]
        if not isinstance(o_map, list) or len(o_map) != 2:
            raise TileQueryError(TileFailure.MALFORMED_RESPONSE)
        map_width, map_height = (integer(v, 1, 4096) for v in o_map)
        tiles = o["tiles"]
        if not isinstance(tiles, list):
            raise TileQueryError(TileFailure.MALFORMED_RESPONSE)
        rows = []
        for row in tiles:
            if not isinstance(row, list) or len(row) != ROW_WIDTH:
                raise TileQueryError(TileFailure.MALFORMED_RESPONSE)
            rows.append(tuple(row))
        return cls(
            validate_request_id(o["request_id"]),
            region,
            cursor,
            schema,
            map_width,
            map_height,
            integer(o["date_before"], 0, 2147483647),
            integer(o["date_after"], 0, 2147483647),
            tuple(rows),
            None if o["next_cursor"] is None else integer(o["next_cursor"], 1, 255),
            o["has_more"],
        )


@dataclass(frozen=True)
class TileClassificationFact:
    """One classified tile; provenance pinned to the schema-2 observation."""

    tile_id: int
    x: int
    y: int
    min_height: int
    slope: int
    tile_class: TileClass
    flags: int
    industry_id: int | None
    owner: int


@dataclass(frozen=True)
class TileClassificationIndex:
    """Complete sweep of classified tiles over one captured rectangle.

    ``unknown_tiles`` counts tiles whose native class the wire could not
    establish; consumers must surface them explicitly
    (``INCOMPLETE_TILE_CLASSIFICATION``) rather than silently reacting.
    """

    region: Region
    map_width: int
    map_height: int
    schema: int
    tiles: tuple[TileClassificationFact, ...]
    date_before: int
    date_after: int

    def __post_init__(self):
        if self.schema != CLASSIFICATION_SCHEMA_VERSION:
            raise TileQueryError(TileFailure.UNSUPPORTED_CLASSIFICATION_SCHEMA)
        expected = self.region.width * self.region.height
        if len(self.tiles) != expected:
            raise TileQueryError(TileFailure.INCOMPLETE_SWEEP)
        seen: set[int] = set()
        for index, tile in enumerate(self.tiles):
            ordinal = index
            x = self.region.x + ordinal % self.region.width
            y = self.region.y + ordinal // self.region.width
            if (
                tile.x != x
                or tile.y != y
                or tile.tile_id != y * self.map_width + x
                or tile.tile_id in seen
            ):
                raise TileQueryError(TileFailure.INVALID_TILE)
            seen.add(tile.tile_id)

    @property
    def by_tile(self) -> dict[int, TileClassificationFact]:
        return {t.tile_id: t for t in self.tiles}

    @property
    def unknown_tiles(self) -> tuple[int, ...]:
        return tuple(t.tile_id for t in self.tiles if t.tile_class is TileClass.UNKNOWN_OCCUPANCY)

    @property
    def class_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for t in self.tiles:
            counts[t.tile_class.value] = counts.get(t.tile_class.value, 0) + 1
        return dict(sorted(counts.items()))

    @classmethod
    def from_pages(
        cls,
        request: TileClassificationRequest,
        responses: tuple[TileClassificationResponse, ...],
    ) -> TileClassificationIndex:
        """Compose a complete in-order index; fail closed on gaps/duplicates."""
        region = request.region
        if not responses:
            raise TileQueryError(TileFailure.CLASSIFICATION_UNAVAILABLE)
        map_width = responses[0].map_width
        map_height = responses[0].map_height
        for response in responses:
            if response.request_id != request.request_id:
                raise TileQueryError(TileFailure.REQUEST_ID_MISMATCH)
            if response.region != region:
                raise TileQueryError(TileFailure.MALFORMED_RESPONSE)
            if response.schema != CLASSIFICATION_SCHEMA_VERSION:
                raise TileQueryError(TileFailure.UNSUPPORTED_CLASSIFICATION_SCHEMA)
            if response.map_width != map_width or response.map_height != map_height:
                raise TileQueryError(TileFailure.MALFORMED_RESPONSE)
        for previous, response in zip(responses, responses[1:], strict=False):
            if response.cursor <= previous.cursor:
                raise TileQueryError(TileFailure.CURSOR_MISMATCH)
        rows: dict[int, TileClassificationFact] = {}
        date_before: int | None = None
        date_after: int | None = None
        for response in responses:
            geometry = response.geometry
            for tile, tile_class, industry, owner in response.classification:
                if tile in rows:
                    raise TileQueryError(TileFailure.DUPLICATE_TILE)
                elevation, slope, flags = geometry[tile]
                rows[tile] = TileClassificationFact(
                    tile_id=tile,
                    x=tile % response.map_width,
                    y=tile // response.map_width,
                    min_height=elevation,
                    slope=slope,
                    tile_class=tile_class,
                    flags=flags,
                    industry_id=industry,
                    owner=owner,
                )
            date_after = response.date_after
            date_before = response.date_before if date_before is None else date_before
        ordered: list[TileClassificationFact] = []
        expected = region.width * region.height
        for ordinal in range(expected):
            x = region.x + ordinal % region.width
            y = region.y + ordinal // region.width
            fact = rows.get(y * map_width + x)
            if fact is None:
                raise TileQueryError(TileFailure.INCOMPLETE_SWEEP)
            ordered.append(fact)
        if len(ordered) != expected or len(rows) != expected:
            raise TileQueryError(TileFailure.INCOMPLETE_SWEEP)
        return cls(
            region=region,
            map_width=map_width,
            map_height=map_height,
            schema=CLASSIFICATION_SCHEMA_VERSION,
            tiles=tuple(ordered),
            date_before=int(date_before or 0),
            date_after=int(date_after or 0),
        )


def classification_json(index: TileClassificationIndex) -> str:
    """Stable JSON projection for diagnostics output (no digest invention)."""
    return json.dumps(
        {
            "schema": index.schema,
            "region": selector(index.region),
            "map": [index.map_width, index.map_height],
            "date_before": index.date_before,
            "date_after": index.date_after,
            "class_counts": index.class_counts,
            "unknown_tiles": list(index.unknown_tiles),
            "tiles": [
                [
                    t.tile_id,
                    t.x,
                    t.y,
                    t.min_height,
                    t.slope,
                    t.tile_class.value,
                    t.flags,
                    t.industry_id,
                    t.owner,
                ]
                for t in index.tiles
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def tile_classes(index: TileClassificationIndex) -> dict[int, TileClass]:
    return {t.tile_id: t.tile_class for t in index.tiles}


def tile_flags(index: TileClassificationIndex) -> dict[int, int]:
    """Raw native predicate masks for the assessor's projection-coherence gate."""
    return {t.tile_id: t.flags for t in index.tiles}


# --- Task A: receipt, correlation, sweep binding (offline wire layer) --------

SWEEP_VERSION = "tile-classification-sweep-v1"

# Derived from MAX_TILES(256)/MAX_COVERAGE(512): a 450-tile Seed 17 region
# needs 90 pages; the limit is the same census ceiling, never silently grown.
CLASSIFICATION_MAX_REGION_TILES = 512
CLASSIFICATION_PAGE_LIMIT = (CLASSIFICATION_MAX_REGION_TILES + PAGE_SIZE - 1) // PAGE_SIZE
CLASSIFICATION_TOTAL_RESPONSE_BYTES_LIMIT = CLASSIFICATION_PAGE_LIMIT * MAX_RESPONSE_BYTES

CLASSIFICATION_NETWORK_SEQUENCE = (
    "TILE_CLASSIFICATION_REQUEST_SENT",
    "TILE_CLASSIFICATION_RESPONSE_RECEIVED",
    "CLASSIFICATION_RECEIPT_CREATED",
    "CLASSIFICATION_RECEIPT_VALIDATED",
)

WELCOME_IDENTITY_KEYS = (
    "seed",
    "width",
    "height",
    "landscape",
    "revision",
    "start_day",
)


def projection_disagrees(tile_fact: TileFact, flags: int) -> bool:
    """Exact check that schema-2 raw bits project into the legacy TileFact.

    The schema-1 projected booleans are defined functions of the schema-2
    predicate mask: projected ground/transport bits carry over, the road bit
    is the OR of the three road bits, and ``buildable`` is the buildable bit
    unless the native house/station bits force it false (the historical
    schema-1 collapse that the classification schema exists to remove). Any
    disagreement means the two records could not have been captured in the
    same instant, so the tile stays UNKNOWN instead of picking a side.
    """

    def bit(name: str) -> bool:
        return bool(flags & (1 << flags_index(name)))

    direct = (
        (bit("water"), tile_fact.water),
        (bit("coast"), tile_fact.coast),
        (bit("tree"), tile_fact.tree),
        (bit("farm"), tile_fact.farm),
        (bit("rock"), tile_fact.rock),
        (bit("rough"), tile_fact.rough),
        (bit("rail"), tile_fact.rail),
        (bit("water_transport"), tile_fact.water_transport),
        (bit("airport"), tile_fact.air_transport),
        (
            bit("road_tile") or bit("road_track") or bit("road_src_type"),
            tile_fact.road,
        ),
    )
    if any(wire != projected for wire, projected in direct):
        return True
    projected_buildable = bit("buildable") and not (bit("house") or bit("station"))
    return projected_buildable is not bool(tile_fact.buildable)


@dataclass(frozen=True)
class TileClassificationReceipt:
    """Per-page evidence binding between one request and its response."""

    request_id: str
    schema: int
    request_payload_sha256: str
    response_payload_sha256: str

    @classmethod
    def correlate(cls, request: bytes, response: bytes) -> TileClassificationReceipt:
        q = TileClassificationRequest.parse(request)
        if len(response) > MAX_RESPONSE_BYTES:
            raise TileQueryError(TileFailure.RESPONSE_LIMIT_EXCEEDED)
        # Correlation must precede propagating a bounded native error, matching
        # the v1 receipt convention exactly.
        try:
            raw = json.loads(response)
            identity = raw.get("request_id")
            schema = raw.get("schema")
        except (ValueError, AttributeError) as e:
            raise TileQueryError(TileFailure.MALFORMED_RESPONSE) from e
        if identity != q.request_id:
            raise TileQueryError(TileFailure.REQUEST_ID_MISMATCH)
        if (
            integer(
                schema,
                CLASSIFICATION_SCHEMA_VERSION,
                CLASSIFICATION_SCHEMA_VERSION,
                TileFailure.UNSUPPORTED_CLASSIFICATION_SCHEMA,
            )
            != CLASSIFICATION_SCHEMA_VERSION
        ):
            raise TileQueryError(TileFailure.UNSUPPORTED_CLASSIFICATION_SCHEMA)
        r = TileClassificationResponse.parse(response)
        if (r.region, r.cursor, r.schema) != (q.region, q.cursor, q.schema):
            raise TileQueryError(TileFailure.CURSOR_MISMATCH)
        return cls(
            q.request_id,
            q.schema,
            hashlib.sha256(request).hexdigest(),
            hashlib.sha256(response).hexdigest(),
        )


@dataclass(frozen=True)
class TileClassificationExchange:
    request_payload: bytes
    response_payload: bytes
    receipt: TileClassificationReceipt
    ordered_sequence: tuple[str, ...] = CLASSIFICATION_NETWORK_SEQUENCE
    protocol_operations: int = 4
    requests_sent: int = 1
    matching_responses: int = 1
    retries: int = 0

    @property
    def response(self) -> TileClassificationResponse:
        return TileClassificationResponse.parse(self.response_payload)

    def validate(self):
        if (
            self.ordered_sequence != CLASSIFICATION_NETWORK_SEQUENCE
            or (self.requests_sent, self.matching_responses, self.retries) != (1, 1, 0)
            or type(self.protocol_operations) is not int
            or not 4 <= self.protocol_operations <= 8
            or self.receipt
            != TileClassificationReceipt.correlate(self.request_payload, self.response_payload)
        ):
            raise TileQueryError(TileFailure.ACCOUNTING_LIMIT_EXCEEDED)


@dataclass(frozen=True)
class TileClassificationSweep:
    # NOTE: the ``tile_classes``/``tile_flags`` properties expose the merged
    # census projections for the assessor and deliberately shadow nothing:
    # inside their bodies the module-level ``tile_classes``/``tile_flags``
    # functions over a single index are still the callable symbols.
    """Receipt-verified, TileFact-coherent complete classification census.

    A census observation covers one captured rectangle. Because a single
    classification request expresses at most 256 tiles (the shared v1
    rectangle budget) and the Seed 17 census region is a 450-tile
    ``random-rectangle-512-v1`` capture, a census is acquired as a
    deterministic multi-band request plan (``classification_plan``): every
    band is its own bounded request sequence and its own complete
    ``TileClassificationIndex``; the sweep aggregates them without weakening
    any per-page contract.

    ``bound`` is only true when the plan is complete, the observed welcome
    identity matches the retained one and no tile contradicts the retained
    ``TileFact`` observations (same capture-instant gate). Contradictory,
    missing or duplicated observations are rejected, never repaired, renamed
    or downgraded silently; the sweep keeps the evidence either way with the
    exact failure inventory.
    """

    observed_welcome: tuple[tuple[str, int | str], ...]
    retained_welcome: tuple[tuple[str, int | str], ...]
    retained_facts_digest: str
    region: Region
    pages: int
    request_digests: tuple[str, ...]
    response_digests: tuple[str, ...]
    receipts: tuple[TileClassificationReceipt, ...]
    indexes: tuple[TileClassificationIndex, ...]
    coherence_failures: tuple[tuple[int, str], ...]
    version: str = SWEEP_VERSION

    @property
    def bound(self) -> bool:
        return not self.coherence_failures

    @property
    def world_identity_mismatch(self) -> bool:
        return any(
            reason == "WORLD_IDENTITY_MISMATCH" or reason.startswith("WORLD_IDENTITY_MISMATCH:")
            for _, reason in self.coherence_failures
        )

    @property
    def unknown_tiles(self) -> tuple[int, ...]:
        merged: list[int] = []
        for index in self.indexes:
            merged.extend(index.unknown_tiles)
        return tuple(merged)

    @property
    def class_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for index in self.indexes:
            for name, count in index.class_counts.items():
                counts[name] = counts.get(name, 0) + count
        return dict(sorted(counts.items()))

    @property
    def tile_classes(self) -> dict[int, TileClass]:
        classes: dict[int, TileClass] = {}
        for index in self.indexes:
            classes.update(tile_classes(index))
        return classes

    @property
    def tile_flags(self) -> dict[int, int]:
        flags: dict[int, int] = {}
        for index in self.indexes:
            flags.update(tile_flags(index))
        return flags

    @property
    def facts(self) -> tuple[TileClassificationFact, ...]:
        return tuple(fact for index in self.indexes for fact in index.tiles)

    def require_bound(self) -> tuple[dict[int, TileClass], dict[int, int]]:
        """Assessor input gate: only a fully bound census may be fused."""
        if not self.bound:
            raise TileQueryError(TileFailure.ACCOUNTING_LIMIT_EXCEEDED)
        return self.tile_classes, self.tile_flags

    def completeness_summary(self) -> str:
        payload = {
            "version": self.version,
            "schema": CLASSIFICATION_SCHEMA_VERSION,
            "region": list(selector(self.region)),
            "bands": len(self.indexes),
            "pages": self.pages,
            "tiles": len(self.facts),
            "class_counts": self.class_counts,
            "unknown_tiles": list(self.unknown_tiles),
            "coherence_failures": [[tile, reason] for tile, reason in self.coherence_failures],
            "bound": self.bound,
            "world_identity_mismatch": self.world_identity_mismatch,
            "retained_facts_digest": self.retained_facts_digest,
            "receipts": len(self.receipts),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.completeness_summary().encode()).hexdigest()

    @classmethod
    def verify_identity(cls, retained_welcome: dict, observed_welcome: dict) -> tuple[str, ...]:
        """Early world-identity gate; same-seed recipes are not equal worlds."""
        failures: list[tuple[int, str]] = []
        for key in WELCOME_IDENTITY_KEYS:
            if key not in retained_welcome:
                continue
            if retained_welcome[key] != observed_welcome.get(key):
                failures.append((-1, f"WORLD_IDENTITY_MISMATCH:{key}"))
        return failures

    @classmethod
    def record(
        cls,
        requests: tuple[TileClassificationRequest, ...],
        exchanges: tuple[TileClassificationExchange, ...],
        *,
        retained_facts: SupplementalPlanningFacts,
        retained_facts_digest: str,
        retained_welcome: dict,
        observed_welcome: dict,
    ) -> TileClassificationSweep:
        region = retained_facts.region
        total = region.width * region.height
        if not isinstance(total, int) or total > CLASSIFICATION_MAX_REGION_TILES:
            raise TileQueryError(TileFailure.COVERAGE_LIMIT_EXCEEDED)
        if not requests or len(requests) != len(exchanges):
            raise TileQueryError(TileFailure.INCOMPLETE_SWEEP)
        plan = classification_plan(region, requests[0].request_id)
        if tuple(requests) != plan or len(exchanges) != len(plan):
            raise TileQueryError(TileFailure.INCOMPLETE_SWEEP)
        if len(requests) > CLASSIFICATION_PAGE_LIMIT:
            raise TileQueryError(TileFailure.ACCOUNTING_LIMIT_EXCEEDED)
        total_bytes = sum(len(exchange.response_payload) for exchange in exchanges)
        if total_bytes > CLASSIFICATION_TOTAL_RESPONSE_BYTES_LIMIT:
            raise TileQueryError(TileFailure.ACCOUNTING_LIMIT_EXCEEDED)

        failures: list[tuple[int, str]] = list(
            cls.verify_identity(retained_welcome, observed_welcome)
        )
        request_digests: list[str] = []
        response_digests: list[str] = []
        receipts: list[TileClassificationReceipt] = []
        groups: dict[Region, list[TileClassificationResponse]] = {}
        group_requests: dict[Region, TileClassificationRequest] = {}
        for request, exchange in zip(requests, exchanges, strict=True):
            exchange.validate()
            if exchange.request_payload != request.to_bytes():
                # The received buffer must be the exact pinned plan bytes, not
                # merely a semantically equal re-encoding of one.
                raise TileQueryError(TileFailure.MALFORMED_RESPONSE)
            if exchange.receipt.request_id != request.request_id:
                raise TileQueryError(TileFailure.REQUEST_ID_MISMATCH)
            response = exchange.response
            if response.request_id != request.request_id or (
                response.region,
                response.cursor,
                response.schema,
            ) != (request.region, request.cursor, request.schema):
                raise TileQueryError(TileFailure.REQUEST_ID_MISMATCH)
            request_digests.append(hashlib.sha256(request.to_bytes()).hexdigest())
            response_digests.append(hashlib.sha256(exchange.response_payload).hexdigest())
            receipts.append(exchange.receipt)
            groups.setdefault(request.region, []).append(response)
            group_requests.setdefault(request.region, request)

        indexes: list[TileClassificationIndex] = []
        for band in groups:
            indexes.append(
                TileClassificationIndex.from_pages(group_requests[band], tuple(groups[band]))
            )

        retained_rows = {t.tile_id: t for t in retained_facts.tiles}
        for index in indexes:
            for classification in index.tiles:
                fact = retained_rows.get(classification.tile_id)
                if fact is None:
                    failures.append((classification.tile_id, "TILE_FACT_MISSING"))
                    continue
                if classification.min_height != fact.min_height:
                    failures.append((classification.tile_id, "HEIGHT_DIFFERS_FROM_TILE_FACT"))
                if classification.slope != fact.slope:
                    failures.append((classification.tile_id, "SLOPE_DIFFERS_FROM_TILE_FACT"))
                if classification.industry_id != fact.industry_id:
                    failures.append((classification.tile_id, "INDUSTRY_DIFFERS_FROM_TILE_FACT"))
                if projection_disagrees(fact, classification.flags):
                    failures.append((classification.tile_id, "PROJECTED_FLAGS_DIFFER"))
        return cls(
            observed_welcome=tuple(sorted(observed_welcome.items())),
            retained_welcome=tuple(sorted(retained_welcome.items())),
            retained_facts_digest=retained_facts_digest,
            region=region,
            pages=len(requests),
            request_digests=tuple(request_digests),
            response_digests=tuple(response_digests),
            receipts=tuple(receipts),
            indexes=tuple(indexes),
            coherence_failures=tuple(failures),
        )


def classification_bands(region: Region) -> tuple[tuple[int, int, int, int], ...]:
    """Deterministic guillotine band rectangles covering ``region`` once.

    Each band respects the shared 256-tile request budget (``rectangle``). Bands
    run along the y axis when the width fits the budget and along the x axis
    otherwise. The schema-2 census plan and the fallback same-session v1 facts
    bank share this exact banding so both wire types address every census tile
    through the same bounded regions.
    """
    if not region.width or not region.height:
        raise TileQueryError(TileFailure.INVALID_REGION)
    if region.width * region.height > CLASSIFICATION_MAX_REGION_TILES:
        raise TileQueryError(TileFailure.COVERAGE_LIMIT_EXCEEDED)
    bands: list[tuple[int, int, int, int]] = []
    if region.width <= 256:
        band_height = max(1, 256 // region.width)
        for offset in range(0, region.height, band_height):
            bands.append(
                (
                    region.x,
                    region.y + offset,
                    region.width,
                    min(band_height, region.height - offset),
                )
            )
    else:
        band_width = max(1, 256 // region.height)
        for offset in range(0, region.width, band_width):
            bands.append(
                (
                    region.x + offset,
                    region.y,
                    min(band_width, region.width - offset),
                    region.height,
                )
            )
    return tuple(bands)


def classification_plan(region: Region, request_id: str) -> tuple[TileClassificationRequest, ...]:
    """Deterministic bounded request sequence covering ``region`` once.

    The census rectangle is split into guillotine bands whose area respects
    the shared 256-tile request budget (``rectangle``); every band is paginated
    with PAGE_SIZE cursors from 0 under its own id.
    """
    requests: list[TileClassificationRequest] = []
    for bx, by, bw, bh in classification_bands(region):
        pages = (bw * bh + PAGE_SIZE - 1) // PAGE_SIZE
        for ordinal in range(pages):
            requests.append(
                TileClassificationRequest(
                    request_id,
                    Region(x=bx, y=by, width=bw, height=bh),
                    ordinal * PAGE_SIZE,
                    CLASSIFICATION_SCHEMA_VERSION,
                )
            )
    if len(requests) > CLASSIFICATION_PAGE_LIMIT:
        raise TileQueryError(TileFailure.ACCOUNTING_LIMIT_EXCEEDED)
    return tuple(requests)
