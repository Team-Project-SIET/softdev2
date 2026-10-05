"""Version-one no-mutation ping/ACK envelopes, independent of sockets and planners."""

import hashlib
import json
import re
from dataclasses import dataclass

PROTOCOL_VERSION = 1
MAX_PAYLOAD_BYTES = 512
MAX_REQUEST_ID_BYTES = 64
_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


class BridgeProtocolError(ValueError):
    """Unsupported protocol/version/type or failed response correlation."""


class MalformedMessage(BridgeProtocolError):
    """Invalid JSON, schema, size, or request identifier."""


def validate_request_id(request_id: object) -> str:
    if not isinstance(request_id, str) or _REQUEST_ID.fullmatch(request_id) is None:
        raise MalformedMessage("request_id must be 1-64 safe ASCII characters")
    return request_id


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise MalformedMessage("duplicate JSON key")
        result[key] = value
    return result


def _object(payload: bytes, message_type: str, fields: set[str]) -> dict[str, object]:
    if not 0 < len(payload) <= MAX_PAYLOAD_BYTES:
        raise MalformedMessage("payload exceeds application byte limit")
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise MalformedMessage("invalid bridge JSON") from error
    if not isinstance(value, dict) or set(value) != fields:
        raise MalformedMessage("invalid bridge envelope fields")
    if type(value["protocol"]) is not int or value["protocol"] != PROTOCOL_VERSION:
        raise BridgeProtocolError("unsupported bridge protocol version")
    if value["type"] != message_type:
        raise BridgeProtocolError("unsupported bridge message type")
    validate_request_id(value["request_id"])
    return value


def _serialize(value: dict[str, object]) -> bytes:
    result = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    if len(result) > MAX_PAYLOAD_BYTES:
        raise MalformedMessage("serialized payload exceeds application byte limit")
    return result


@dataclass(frozen=True)
class PingRequest:
    request_id: str

    def __post_init__(self) -> None:
        validate_request_id(self.request_id)

    def to_bytes(self) -> bytes:
        return _serialize(
            {"protocol": PROTOCOL_VERSION, "type": "ping", "request_id": self.request_id}
        )

    @classmethod
    def parse(cls, payload: bytes) -> PingRequest:
        value = _object(payload, "ping", {"protocol", "type", "request_id"})
        return cls(validate_request_id(value["request_id"]))


@dataclass(frozen=True)
class Ack:
    request_id: str

    def __post_init__(self) -> None:
        validate_request_id(self.request_id)

    @property
    def status(self) -> str:
        return "ok"

    def to_bytes(self) -> bytes:
        return _serialize(
            {
                "protocol": PROTOCOL_VERSION,
                "type": "ack",
                "request_id": self.request_id,
                "status": "ok",
            }
        )

    @classmethod
    def parse(cls, payload: bytes) -> Ack:
        value = _object(payload, "ack", {"protocol", "type", "request_id", "status"})
        if value["status"] != "ok":
            raise BridgeProtocolError("unsupported ACK status")
        return cls(validate_request_id(value["request_id"]))


def handle_ping(payload: bytes) -> bytes:
    """Pure controlled model of the bridge; repeated pings produce identical ACKs."""
    return Ack(PingRequest.parse(payload).request_id).to_bytes()


@dataclass(frozen=True)
class CommunicationReceipt:
    protocol_version: int
    request_id: str
    request_payload_sha256: str
    response_payload_sha256: str
    response_type: str
    status: str

    @classmethod
    def correlate(cls, request: bytes, response: bytes) -> CommunicationReceipt:
        ping = PingRequest.parse(request)
        ack = Ack.parse(response)
        if ping.request_id != ack.request_id:
            raise BridgeProtocolError("ACK request_id does not match pending request")
        return cls(
            PROTOCOL_VERSION,
            ping.request_id,
            hashlib.sha256(request).hexdigest(),
            hashlib.sha256(response).hexdigest(),
            "ack",
            ack.status,
        )
