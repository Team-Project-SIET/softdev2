"""Protocol-one read-only map dimensions and independent Admin verification."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from app.simulation.openttd.observation_identity import BridgePackage, RuntimeIdentity
from app.simulation.openttd.observation_protocol import (
    PROTOCOL_VERSION,
    BridgeProtocolError,
    MalformedMessage,
    _object,
    _serialize,
    validate_request_id,
)

if TYPE_CHECKING:
    from app.simulation.openttd.admin_protocol import ServerWelcome
    from app.simulation.openttd.world_info_evidence import WorldInfoEvidence


def validate_dimension(value: object) -> int:
    # Positive uint16 dimension, as independently encoded by SERVER_WELCOME.
    # The engine also requires powers of two (15.3 Map::Allocate).
    if type(value) is not int or not 0 < value < 2**16 or value & (value - 1):
        raise MalformedMessage("map dimension must be a positive uint16 power of two")
    return value


@dataclass(frozen=True)
class WorldInfoRequest:
    request_id: str

    def __post_init__(self) -> None:
        validate_request_id(self.request_id)

    def to_bytes(self) -> bytes:
        return _serialize(
            {"protocol": PROTOCOL_VERSION, "type": "world_info", "request_id": self.request_id}
        )

    @classmethod
    def parse(cls, payload: bytes) -> WorldInfoRequest:
        value = _object(payload, "world_info", {"protocol", "type", "request_id"})
        return cls(validate_request_id(value["request_id"]))


@dataclass(frozen=True)
class WorldInfoResponse:
    request_id: str
    map_width: int
    map_height: int

    def __post_init__(self) -> None:
        validate_request_id(self.request_id)
        validate_dimension(self.map_width)
        validate_dimension(self.map_height)

    @property
    def status(self) -> str:
        return "ok"

    def to_bytes(self) -> bytes:
        return _serialize(
            {
                "protocol": PROTOCOL_VERSION,
                "type": "world_info_result",
                "request_id": self.request_id,
                "status": self.status,
                "map_width": self.map_width,
                "map_height": self.map_height,
            }
        )

    @classmethod
    def parse(cls, payload: bytes) -> WorldInfoResponse:
        value = _object(
            payload,
            "world_info_result",
            {"protocol", "type", "request_id", "status", "map_width", "map_height"},
        )
        if value["status"] != "ok":
            raise BridgeProtocolError("unsupported world_info status")
        return cls(
            validate_request_id(value["request_id"]),
            validate_dimension(value["map_width"]),
            validate_dimension(value["map_height"]),
        )


@dataclass(frozen=True)
class WorldInfoReceipt:
    """Transport correlation only; deliberately separate from the old ACK receipt."""

    protocol_version: int
    request_id: str
    request_payload_sha256: str
    response_payload_sha256: str
    response_type: str = "world_info_result"
    status: str = "ok"

    @classmethod
    def correlate(cls, request: bytes, response: bytes) -> WorldInfoReceipt:
        query = WorldInfoRequest.parse(request)
        result = WorldInfoResponse.parse(response)
        if query.request_id != result.request_id:
            raise BridgeProtocolError("world_info request_id mismatch")
        return cls(
            1,
            query.request_id,
            hashlib.sha256(request).hexdigest(),
            hashlib.sha256(response).hexdigest(),
        )


NETWORK_SEQUENCE = ("REQUEST_SENT", "NETWORK_RESPONSE_RECEIVED", "RECEIPT_CREATED")


@dataclass(frozen=True)
class WorldInfoExchange:
    request_payload: bytes
    response_payload: bytes
    receipt: WorldInfoReceipt
    ordered_sequence: tuple[str, ...]
    requests_sent: int
    matching_responses: int
    retries: int

    @property
    def response(self) -> WorldInfoResponse:
        return WorldInfoResponse.parse(self.response_payload)

    def validate(self) -> None:
        if self.ordered_sequence != NETWORK_SEQUENCE or (
            self.requests_sent,
            self.matching_responses,
            self.retries,
        ) != (1, 1, 0):
            raise BridgeProtocolError("Incomplete/duplicate/retried world_info network evidence")
        if self.receipt != WorldInfoReceipt.correlate(self.request_payload, self.response_payload):
            raise BridgeProtocolError("World-info receipt does not bind the network response")


@dataclass(frozen=True)
class WorldInfoSourceReference:
    file: str
    sha256: str


@dataclass(frozen=True)
class WorldInfoVerification:
    request_id: str
    response_digest: str
    reported_dimensions: tuple[int, int]
    independently_observed_dimensions: tuple[int, int]
    dimensions_match: bool
    runtime_identity: RuntimeIdentity
    bridge_identity: BridgePackage
    independent_source: str
    internal_log_digest: str
    source_evidence: tuple[WorldInfoSourceReference, ...]

    @property
    def width_match(self) -> bool:
        return self.reported_dimensions[0] == self.independently_observed_dimensions[0]

    @property
    def height_match(self) -> bool:
        return self.reported_dimensions[1] == self.independently_observed_dimensions[1]

    @property
    def verified(self) -> bool:
        return self.dimensions_match and self.width_match and self.height_match

    @property
    def status(self) -> str:
        return "verified" if self.dimensions_match else "dimension_mismatch"

    def require_match(self) -> None:
        if not self.dimensions_match:
            raise BridgeProtocolError("GameScript/Admin map dimension mismatch")


def verify_world_info(
    exchange: WorldInfoExchange,
    evidence: WorldInfoEvidence,
    welcome: ServerWelcome,
    *,
    runtime: RuntimeIdentity,
    bridge: BridgePackage,
    welcome_digest: str | None = None,
) -> WorldInfoVerification:
    """Two locally ordered channels plus a separately supplied trusted WELCOME.

    Caller obtains welcome from its authenticated secure session in the same runtime;
    this function never manufactures Admin observations from GameScript values.
    """
    exchange.validate()
    response = exchange.response
    evidence.require_complete(response)
    validate_dimension(welcome.width)
    validate_dimension(welcome.height)
    if welcome.revision != runtime.version or runtime.version != "15.3":
        raise BridgeProtocolError("Independent runtime identity mismatch")
    reported = (response.map_width, response.map_height)
    observed = (welcome.width, welcome.height)
    return WorldInfoVerification(
        response.request_id,
        exchange.receipt.response_payload_sha256,
        reported,
        observed,
        reported == observed,
        runtime,
        bridge,
        "SERVER_WELCOME",
        evidence.raw_evidence_digest,
        (
            WorldInfoSourceReference(
                "world-info-response.json", exchange.receipt.response_payload_sha256
            ),
            WorldInfoSourceReference(evidence.source_log, evidence.raw_evidence_digest),
            WorldInfoSourceReference(
                "welcome-evidence.json",
                welcome_digest
                or hashlib.sha256(json.dumps(asdict(welcome), sort_keys=True).encode()).hexdigest(),
            ),
        ),
    )
