"""Read-only cargo page protocol; native four-byte labels use uppercase byte hex."""

from dataclasses import asdict, dataclass

from app.simulation.openttd.gamescript_protocol import _object, _serialize, validate_request_id
from app.simulation.openttd.industry_page import _integer

MAX_CARGO_ID = 63
DEFAULT_CARGO_PAGE_SIZE = 2
MAX_CARGO_PAGE_SIZE = 4  # 186 envelope + N*76 records + N-1 commas: 493; five 570.


@dataclass(frozen=True)
class CargoPageRequest:
    request_id: str
    after_id: int | None = None
    limit: int = DEFAULT_CARGO_PAGE_SIZE

    def __post_init__(self):
        validate_request_id(self.request_id)
        if self.after_id is not None:
            _integer(self.after_id, MAX_CARGO_ID, "cargo cursor")
        if _integer(self.limit, MAX_CARGO_PAGE_SIZE, "cargo page limit") == 0:
            raise ValueError("cargo page limit must be positive")

    def to_bytes(self) -> bytes:
        return _serialize(dict(protocol=1, type="cargo_page", **asdict(self)))

    @classmethod
    def parse(cls, payload: bytes) -> CargoPageRequest:
        obj = _object(
            payload, "cargo_page", {"protocol", "type", "request_id", "after_id", "limit"}
        )
        return cls(
            validate_request_id(obj["request_id"]),
            None
            if obj["after_id"] is None
            else _integer(obj["after_id"], MAX_CARGO_ID, "cargo cursor"),
            _integer(obj["limit"], MAX_CARGO_PAGE_SIZE, "cargo page limit"),
        )


# Project mask v1: bit i corresponds to the named ScriptCargo class below.
# Special/native bit 15 is not exposed by ScriptCargo and is intentionally absent.
CARGO_CLASS_NAMES = (
    "PASSENGERS",
    "MAIL",
    "EXPRESS",
    "ARMOURED",
    "BULK",
    "PIECE_GOODS",
    "LIQUID",
    "REFRIGERATED",
    "HAZARDOUS",
    "COVERED",
    "OVERSIZED",
    "POWDERIZED",
    "NON_POURABLE",
    "POTABLE",
    "NON_POTABLE",
)


@dataclass(frozen=True)
class CargoCatalogRecord:
    cargo_id: int
    cargo_label: str
    is_freight: bool
    town_effect: int
    cargo_classes: int

    def __post_init__(self):
        import re

        _integer(self.cargo_id, MAX_CARGO_ID, "cargo ID")
        if (
            not isinstance(self.cargo_label, str)
            or re.fullmatch(r"[0-9A-F]{8}", self.cargo_label) is None
        ):
            raise ValueError("label must encode the exact four native bytes as uppercase hex")
        if type(self.is_freight) is not bool:
            raise ValueError("freight must be boolean")
        _integer(self.town_effect, 5, "town effect")
        _integer(self.cargo_classes, 32767, "cargo class mask v1")

    def to_wire(self) -> dict:
        return dict(
            id=self.cargo_id,
            label=self.cargo_label,
            freight=self.is_freight,
            town_effect=self.town_effect,
            classes=self.cargo_classes,
        )


@dataclass(frozen=True)
class CargoPageResponse:
    request_id: str
    cargoes: tuple[CargoCatalogRecord, ...]
    next_after_id: int | None
    has_more: bool

    def __post_init__(self):
        validate_request_id(self.request_id)
        if self.next_after_id is not None:
            _integer(self.next_after_id, MAX_CARGO_ID, "cargo cursor")
        if type(self.cargoes) is not tuple or type(self.has_more) is not bool:
            raise ValueError("immutable cargoes and boolean has_more required")
        if len(self.cargoes) > MAX_CARGO_PAGE_SIZE or any(
            not isinstance(r, CargoCatalogRecord) for r in self.cargoes
        ):
            raise ValueError("invalid cargo records")
        ids = [r.cargo_id for r in self.cargoes]
        if ids != sorted(set(ids)):
            raise ValueError("cargo IDs must be unique and ascending")
        if self.has_more:
            if not ids or self.next_after_id != ids[-1]:
                raise ValueError("has_more requires progress and last-ID cursor")
        elif self.next_after_id is not None:
            raise ValueError("terminal cursor must be null")

    def to_bytes(self) -> bytes:
        return _serialize(
            dict(
                protocol=1,
                type="cargo_page_result",
                request_id=self.request_id,
                status="ok",
                cargoes=[r.to_wire() for r in self.cargoes],
                next_after_id=self.next_after_id,
                has_more=self.has_more,
            )
        )

    @classmethod
    def parse(cls, payload: bytes) -> CargoPageResponse:
        obj = _object(
            payload,
            "cargo_page_result",
            {"protocol", "type", "request_id", "status", "cargoes", "next_after_id", "has_more"},
        )
        if obj["status"] != "ok" or type(obj["cargoes"]) is not list:
            raise ValueError("invalid cargo page status/records")
        records = []
        for item in obj["cargoes"]:
            if not isinstance(item, dict) or set(item) != {
                "id",
                "label",
                "freight",
                "town_effect",
                "classes",
            }:
                raise ValueError("invalid cargo record fields")
            records.append(
                CargoCatalogRecord(
                    item["id"], item["label"], item["freight"], item["town_effect"], item["classes"]
                )
            )
        if type(obj["has_more"]) is not bool:
            raise ValueError("has_more must be boolean")
        return cls(
            validate_request_id(obj["request_id"]),
            tuple(records),
            None
            if obj["next_after_id"] is None
            else _integer(obj["next_after_id"], MAX_CARGO_ID, "cargo cursor"),
            obj["has_more"],
        )

    def validate_page(self, request: CargoPageRequest) -> None:
        if self.request_id != request.request_id:
            raise ValueError("cargo page request_id mismatch")
        if (
            len(self.cargoes) > request.limit
            or self.has_more
            and len(self.cargoes) != request.limit
        ):
            raise ValueError("oversized or short intermediate page")
        if request.after_id is not None and any(
            r.cargo_id <= request.after_id for r in self.cargoes
        ):
            raise ValueError("cargo cursor did not progress")


CARGO_PAGE_NETWORK_SEQUENCE = (
    "CARGO_PAGE_REQUEST_SENT",
    "CARGO_PAGE_RESPONSE_RECEIVED",
    "TRANSPORT_RECEIPT_CREATED",
    "CARGO_PAGE_VALIDATED",
)


@dataclass(frozen=True)
class CargoPageReceipt:
    request_id: str
    request_payload_sha256: str
    response_payload_sha256: str

    @classmethod
    def correlate_transport(cls, request: bytes, response: bytes) -> CargoPageReceipt:
        import hashlib

        query = CargoPageRequest.parse(request)
        obj = _object(
            response,
            "cargo_page_result",
            {"protocol", "type", "request_id", "status", "cargoes", "next_after_id", "has_more"},
        )
        if obj["request_id"] != query.request_id or obj["status"] != "ok":
            raise ValueError("Cargo page transport correlation mismatch")
        return cls(
            query.request_id,
            hashlib.sha256(request).hexdigest(),
            hashlib.sha256(response).hexdigest(),
        )

    @classmethod
    def correlate(cls, request: bytes, response: bytes) -> CargoPageReceipt:
        import hashlib

        query = CargoPageRequest.parse(request)
        CargoPageResponse.parse(response).validate_page(query)
        return cls(
            query.request_id,
            hashlib.sha256(request).hexdigest(),
            hashlib.sha256(response).hexdigest(),
        )


@dataclass(frozen=True)
class CargoPageExchange:
    request_payload: bytes
    response_payload: bytes
    receipt: CargoPageReceipt
    ordered_sequence: tuple[str, ...]
    requests_sent: int = 1
    matching_responses: int = 1
    retries: int = 0
    protocol_operations: int = 4

    @property
    def response(self) -> CargoPageResponse:
        return CargoPageResponse.parse(self.response_payload)

    def validate(self) -> None:
        if (
            self.ordered_sequence != CARGO_PAGE_NETWORK_SEQUENCE
            or (self.requests_sent, self.matching_responses, self.retries) != (1, 1, 0)
            or type(self.protocol_operations) is not int
            or self.protocol_operations < 4
        ):
            raise ValueError("incomplete cargo page network evidence")
        if self.receipt != CargoPageReceipt.correlate(self.request_payload, self.response_payload):
            raise ValueError("cargo page receipt mismatch")
