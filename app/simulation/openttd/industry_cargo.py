"""Compact structural cargo capability DTOs; no dynamic economy or planning state."""

import hashlib
from dataclasses import dataclass

from app.simulation.openttd.gamescript_protocol import (
    BridgeProtocolError,
    MalformedMessage,
    _object,
    _serialize,
    validate_request_id,
)
from app.simulation.openttd.industry_page import MAX_INDUSTRY_ID, _integer

MAX_CARGO_ID = 63  # OpenTTD 15.3 NUM_CARGO=64.
MAX_INDUSTRY_CARGOES = 16  # INDUSTRY_NUM_INPUTS/OUTPUTS, including NewGRFs.
CARGO_NETWORK_SEQUENCE = (
    "INDUSTRY_CARGO_REQUEST_SENT",
    "INDUSTRY_CARGO_RESPONSE_RECEIVED",
    "TRANSPORT_RECEIPT_CREATED",
    "CAPABILITY_VALIDATED",
)


def cargo_ids(values: tuple[int, ...]) -> tuple[int, ...]:
    if type(values) is not tuple or len(values) > MAX_INDUSTRY_CARGOES:
        raise MalformedMessage("invalid cargo capability list")
    for value in values:
        _integer(value, MAX_CARGO_ID, "cargo ID")
    if any(a >= b for a, b in zip(values, values[1:])):
        raise MalformedMessage("cargo IDs must be unique and ascending")
    return values


@dataclass(frozen=True)
class IndustryCargoRequest:
    request_id: str
    industry_id: int

    def __post_init__(self):
        validate_request_id(self.request_id)
        _integer(self.industry_id, MAX_INDUSTRY_ID, "industry ID")

    def to_bytes(self) -> bytes:
        return _serialize(
            dict(
                protocol=1,
                type="industry_cargo",
                request_id=self.request_id,
                industry_id=self.industry_id,
            )
        )

    @classmethod
    def parse(cls, payload: bytes) -> IndustryCargoRequest:
        obj = _object(payload, "industry_cargo", {"protocol", "type", "request_id", "industry_id"})
        return cls(
            validate_request_id(obj["request_id"]),
            _integer(obj["industry_id"], MAX_INDUSTRY_ID, "industry ID"),
        )


@dataclass(frozen=True)
class IndustryCargoCapability:
    industry_id: int
    produces: tuple[int, ...]
    accepts: tuple[int, ...]

    def __post_init__(self):
        _integer(self.industry_id, MAX_INDUSTRY_ID, "industry ID")
        cargo_ids(self.produces)
        cargo_ids(self.accepts)


@dataclass(frozen=True)
class IndustryCargoResponse:
    request_id: str
    capability: IndustryCargoCapability

    def __post_init__(self):
        validate_request_id(self.request_id)
        if not isinstance(self.capability, IndustryCargoCapability):
            raise MalformedMessage("invalid cargo capability")

    def to_bytes(self) -> bytes:
        return _serialize(
            dict(
                protocol=1,
                type="industry_cargo_result",
                request_id=self.request_id,
                status="ok",
                industry_id=self.capability.industry_id,
                produces=list(self.capability.produces),
                accepts=list(self.capability.accepts),
            )
        )

    @classmethod
    def parse(cls, payload: bytes) -> IndustryCargoResponse:
        obj = _object(
            payload,
            "industry_cargo_result",
            {"protocol", "type", "request_id", "status", "industry_id", "produces", "accepts"},
        )
        if (
            obj["status"] != "ok"
            or type(obj["produces"]) is not list
            or type(obj["accepts"]) is not list
        ):
            raise MalformedMessage("invalid cargo response")
        return cls(
            validate_request_id(obj["request_id"]),
            IndustryCargoCapability(
                _integer(obj["industry_id"], MAX_INDUSTRY_ID, "industry ID"),
                tuple(_integer(v, MAX_CARGO_ID, "cargo ID") for v in obj["produces"]),
                tuple(_integer(v, MAX_CARGO_ID, "cargo ID") for v in obj["accepts"]),
            ),
        )


@dataclass(frozen=True)
class IndustryCargoReceipt:
    request_id: str
    request_payload_sha256: str
    response_payload_sha256: str

    @classmethod
    def correlate_transport(cls, request: bytes, response: bytes) -> IndustryCargoReceipt:
        """Bind the bounded envelope and raw bytes before cargo semantic validation."""
        query = IndustryCargoRequest.parse(request)
        obj = _object(
            response,
            "industry_cargo_result",
            {"protocol", "type", "request_id", "status", "industry_id", "produces", "accepts"},
        )
        if (
            obj["request_id"] != query.request_id
            or obj["status"] != "ok"
            or _integer(obj["industry_id"], MAX_INDUSTRY_ID, "industry ID") != query.industry_id
        ):
            raise BridgeProtocolError("industry cargo transport correlation mismatch")
        return cls(
            query.request_id,
            hashlib.sha256(request).hexdigest(),
            hashlib.sha256(response).hexdigest(),
        )

    @classmethod
    def correlate(cls, request: bytes, response: bytes) -> IndustryCargoReceipt:
        query, result = IndustryCargoRequest.parse(request), IndustryCargoResponse.parse(response)
        if (
            query.request_id != result.request_id
            or query.industry_id != result.capability.industry_id
        ):
            raise BridgeProtocolError("industry cargo correlation mismatch")
        return cls(
            query.request_id,
            hashlib.sha256(request).hexdigest(),
            hashlib.sha256(response).hexdigest(),
        )


@dataclass(frozen=True)
class IndustryCargoExchange:
    request_payload: bytes
    response_payload: bytes
    receipt: IndustryCargoReceipt
    ordered_sequence: tuple[str, ...]
    requests_sent: int = 1
    matching_responses: int = 1
    retries: int = 0
    protocol_operations: int = 4

    @property
    def response(self) -> IndustryCargoResponse:
        return IndustryCargoResponse.parse(self.response_payload)

    def validate(self) -> None:
        if (
            self.ordered_sequence != CARGO_NETWORK_SEQUENCE
            or (self.requests_sent, self.matching_responses, self.retries) != (1, 1, 0)
            or type(self.protocol_operations) is not int
            or self.protocol_operations < 4
        ):
            raise BridgeProtocolError("incomplete industry cargo transaction")
        if self.receipt != IndustryCargoReceipt.correlate(
            self.request_payload, self.response_payload
        ):
            raise BridgeProtocolError("industry cargo receipt mismatch")
