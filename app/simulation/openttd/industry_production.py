"""One produced industry/cargo pair's raw native metrics, never planning qualification."""

import hashlib
from dataclasses import asdict, dataclass

from app.simulation.openttd.gamescript_protocol import (
    BridgeProtocolError,
    _object,
    _serialize,
    validate_request_id,
)
from app.simulation.openttd.industry_cargo import MAX_CARGO_ID
from app.simulation.openttd.industry_page import MAX_INDUSTRY_ID, _integer

PRODUCTION_NETWORK_SEQUENCE = (
    "INDUSTRY_PRODUCTION_REQUEST_SENT",
    "INDUSTRY_PRODUCTION_RESPONSE_RECEIVED",
    "TRANSPORT_RECEIPT_CREATED",
    "PRODUCTION_RECORD_VALIDATED",
)
MAX_PRODUCTION_RESPONSE_BYTES = 335  # Exact audited V1 historical metric field set.


@dataclass(frozen=True)
class IndustryProductionRequest:
    request_id: str
    industry_id: int
    cargo_id: int

    def __post_init__(self):
        validate_request_id(self.request_id)
        _integer(self.industry_id, MAX_INDUSTRY_ID, "industry ID")
        _integer(self.cargo_id, MAX_CARGO_ID, "cargo ID")

    def to_bytes(self) -> bytes:
        return _serialize(dict(protocol=1, type="industry_production", **asdict(self)))

    @property
    def request_digest(self) -> str:
        return hashlib.sha256(self.to_bytes()).hexdigest()

    @classmethod
    def parse(cls, payload: bytes):
        obj = _object(
            payload, "industry_production", {"protocol", "type", *cls.__dataclass_fields__}
        )
        return cls(
            validate_request_id(obj["request_id"]),
            _integer(obj["industry_id"], MAX_INDUSTRY_ID, "industry ID"),
            _integer(obj["cargo_id"], MAX_CARGO_ID, "cargo ID"),
        )


@dataclass(frozen=True)
class IndustryProductionRecord:
    industry_id: int
    cargo_id: int
    economy_date_before: int
    economy_date_after: int
    last_month_produced: int
    last_month_transported: int
    last_month_transported_pct: int

    def __post_init__(self):
        for name, maximum in (
            ("industry_id", MAX_INDUSTRY_ID),
            ("cargo_id", MAX_CARGO_ID),
            ("economy_date_before", 2147483647),
            ("economy_date_after", 2147483647),
            ("last_month_produced", 65535),
            ("last_month_transported", 65535),
            ("last_month_transported_pct", 100),
        ):
            _integer(getattr(self, name), maximum, name)
        if self.economy_date_after < self.economy_date_before:
            raise BridgeProtocolError("economy date regression during production read")
        # Native percentage is quantized/clamped. Independent uint16 counters can wrap.
        # Neither transported<=produced nor a synthesized percentage is a wire invariant.

    @property
    def pair(self) -> tuple[int, int]:
        return self.industry_id, self.cargo_id


@dataclass(frozen=True)
class IndustryProductionResponse:
    request_id: str
    record: IndustryProductionRecord

    def __post_init__(self):
        validate_request_id(self.request_id)
        if not isinstance(self.record, IndustryProductionRecord):
            raise BridgeProtocolError("typed production record required")

    def to_bytes(self) -> bytes:
        return _serialize(
            dict(
                protocol=1,
                type="industry_production_result",
                status="ok",
                request_id=self.request_id,
                **asdict(self.record),
            )
        )

    @classmethod
    def parse(cls, payload: bytes):
        fields = set(IndustryProductionRecord.__dataclass_fields__)
        obj = _object(
            payload,
            "industry_production_result",
            {"protocol", "type", "request_id", "status", *fields},
        )
        if obj["status"] != "ok":
            raise BridgeProtocolError("production response not successful")
        return cls(
            validate_request_id(obj["request_id"]),
            IndustryProductionRecord(
                _integer(obj["industry_id"], MAX_INDUSTRY_ID, "industry ID"),
                _integer(obj["cargo_id"], MAX_CARGO_ID, "cargo ID"),
                _integer(obj["economy_date_before"], 2147483647, "economy date before"),
                _integer(obj["economy_date_after"], 2147483647, "economy date after"),
                _integer(obj["last_month_produced"], 65535, "last-month produced"),
                _integer(obj["last_month_transported"], 65535, "last-month transported"),
                _integer(obj["last_month_transported_pct"], 100, "native percentage"),
            ),
        )


@dataclass(frozen=True)
class IndustryProductionReceipt:
    request_id: str
    request_payload_sha256: str
    response_payload_sha256: str

    @classmethod
    def correlate(cls, request: bytes, response: bytes):
        q, r = IndustryProductionRequest.parse(request), IndustryProductionResponse.parse(response)
        if q.request_id != r.request_id or (q.industry_id, q.cargo_id) != r.record.pair:
            raise BridgeProtocolError("production correlation mismatch")
        return cls(
            q.request_id, hashlib.sha256(request).hexdigest(), hashlib.sha256(response).hexdigest()
        )


@dataclass(frozen=True)
class IndustryProductionExchange:
    request_payload: bytes
    response_payload: bytes
    receipt: IndustryProductionReceipt
    ordered_sequence: tuple[str, ...] = PRODUCTION_NETWORK_SEQUENCE
    requests_sent: int = 1
    matching_responses: int = 1
    retries: int = 0
    protocol_operations: int = 4

    @property
    def response(self):
        return IndustryProductionResponse.parse(self.response_payload)

    def validate(self):
        if (
            self.ordered_sequence != PRODUCTION_NETWORK_SEQUENCE
            or (self.requests_sent, self.matching_responses, self.retries) != (1, 1, 0)
            or type(self.protocol_operations) is not int
            or self.protocol_operations < 4
            or len(self.response_payload) > MAX_PRODUCTION_RESPONSE_BYTES
            or self.receipt
            != IndustryProductionReceipt.correlate(self.request_payload, self.response_payload)
        ):
            raise BridgeProtocolError("incomplete production transaction")
