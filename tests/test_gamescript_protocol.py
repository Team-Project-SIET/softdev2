"""Controlled application protocol; no game, TCP connection, or mutation."""

import json

import pytest

from app.simulation.openttd.gamescript_protocol import (
    MAX_PAYLOAD_BYTES,
    Ack,
    BridgeProtocolError,
    CommunicationReceipt,
    MalformedMessage,
    PingRequest,
    handle_ping,
)


def test_canonical_ping_and_duplicate_ack() -> None:
    request = PingRequest("ack-000001")
    assert request.to_bytes() == b'{"protocol":1,"request_id":"ack-000001","type":"ping"}'
    reply = handle_ping(request.to_bytes())
    assert reply == b'{"protocol":1,"request_id":"ack-000001","status":"ok","type":"ack"}'
    assert handle_ping(request.to_bytes()) == reply
    assert Ack.parse(reply).request_id == request.request_id


@pytest.mark.parametrize("request_id", ["", "_leading", "white space", "é", "a" * 65, 3, None])
def test_invalid_request_ids_rejected(request_id) -> None:
    with pytest.raises(MalformedMessage):
        PingRequest(request_id)


@pytest.mark.parametrize(
    "value",
    [
        {},
        [],
        None,
        {"type": "ping", "request_id": "a"},
        {"protocol": 1, "type": "ping"},
        {"protocol": 1, "type": "ping", "request_id": "a", "extra": 0},
        {"protocol": True, "type": "ping", "request_id": "a"},
        {"protocol": 1.0, "type": "ping", "request_id": "a"},
        {"protocol": 2, "type": "ping", "request_id": "a"},
        {"protocol": 1, "type": "build", "request_id": "a"},
    ],
)
def test_strict_request_envelope_rejected(value) -> None:
    with pytest.raises(BridgeProtocolError):
        PingRequest.parse(json.dumps(value).encode())


@pytest.mark.parametrize(
    "payload",
    [
        b"{",
        b"\xff",
        b'{"protocol":1,"protocol":1,"type":"ping","request_id":"a"}',
        b'{"protocol":NaN,"type":"ping","request_id":"a"}',
    ],
)
def test_malformed_json_rejected(payload: bytes) -> None:
    with pytest.raises(BridgeProtocolError):
        PingRequest.parse(payload)


def test_exact_size_boundary_and_maximum_reply() -> None:
    request = PingRequest("a" * 64)
    raw = request.to_bytes()
    at_limit = raw + b" " * (MAX_PAYLOAD_BYTES - len(raw))
    assert PingRequest.parse(at_limit) == request
    with pytest.raises(MalformedMessage):
        PingRequest.parse(at_limit + b" ")
    reply = handle_ping(at_limit)
    assert len(reply) == 121 < 512 < 1450
    assert Ack.parse(reply).request_id == "a" * 64
    with pytest.raises(MalformedMessage):
        Ack.parse(reply + b" " * (513 - len(reply)))


def test_receipt_correlation_and_digests() -> None:
    request = PingRequest("ack-000001").to_bytes()
    reply = handle_ping(request)
    receipt = CommunicationReceipt.correlate(request, reply)
    assert receipt == CommunicationReceipt.correlate(request, reply)
    assert receipt.protocol_version == 1
    assert len(receipt.request_payload_sha256) == len(receipt.response_payload_sha256) == 64
    assert receipt.request_payload_sha256 != receipt.response_payload_sha256
    with pytest.raises(BridgeProtocolError, match="does not match"):
        CommunicationReceipt.correlate(request, Ack("other").to_bytes())


@pytest.mark.parametrize(
    "changes",
    [
        dict(protocol=2),
        dict(type="ping"),
        dict(status="failed"),
        dict(request_id=""),
        dict(extra=1),
    ],
)
def test_strict_ack_rejects_invalid_envelopes(changes) -> None:
    value = dict(protocol=1, type="ack", status="ok", request_id="a") | changes
    with pytest.raises(BridgeProtocolError):
        Ack.parse(json.dumps(value).encode())
