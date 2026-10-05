from dataclasses import replace

import pytest
from test_gamescript_proof_evidence import REQUEST_ID, native_log

from app.simulation.openttd.gamescript_protocol import Ack, CommunicationReceipt, PingRequest
from app.simulation.openttd.proof.causality import NetworkProofEvidence, validate_proof
from app.simulation.openttd.proof.gamescript_evidence import parse_gamescript_evidence


def channels():
    request = PingRequest(REQUEST_ID).to_bytes()
    response = Ack(REQUEST_ID).to_bytes()
    network = NetworkProofEvidence(
        request,
        response,
        CommunicationReceipt.correlate(request, response),
        ("REQUEST_SENT", "NETWORK_ACK_RECEIVED", "RECEIPT_CREATED"),
        1,
        1,
        0,
        (),
    )
    return parse_gamescript_evidence(native_log(), REQUEST_ID), network


def test_two_correlated_chains_accepted_without_cross_channel_clock():
    gs, network = channels()
    proof = validate_proof(gs, network)
    assert proof.request_id == REQUEST_ID and proof.protocol == 1
    assert proof.request_type == "ping" and proof.ack_type == "ack" and proof.ack_status == "ok"


@pytest.mark.parametrize(
    "sequence",
    [
        ("NETWORK_ACK_RECEIVED", "REQUEST_SENT", "RECEIPT_CREATED"),
        ("REQUEST_SENT", "RECEIPT_CREATED", "NETWORK_ACK_RECEIVED"),
        ("REQUEST_SENT", "RECEIPT_CREATED"),
        ("REQUEST_SENT", "NETWORK_ACK_RECEIVED"),
    ],
)
def test_invalid_or_incomplete_network_chain_rejected(sequence):
    gs, network = channels()
    with pytest.raises(ValueError):
        validate_proof(gs, replace(network, ordered_sequence=sequence))


@pytest.mark.parametrize(
    "field,value",
    [
        ("requests_sent", 0),
        ("requests_sent", 2),
        ("matching_acks", 0),
        ("matching_acks", 2),
        ("retries", 1),
        ("response_payload", None),
        ("receipt", None),
    ],
)
def test_missing_ack_receipt_or_extra_request_retry_rejected(field, value):
    gs, network = channels()
    with pytest.raises(ValueError):
        validate_proof(gs, replace(network, **{field: value}))


@pytest.mark.parametrize(
    "field,value",
    [
        ("request_id", "wrong"),
        ("protocol", 2),
        ("request_type", "build"),
        ("ack_type", "result"),
        ("ack_status", "failed"),
    ],
)
def test_cross_channel_semantic_mismatch_rejected(field, value):
    gs, network = channels()
    with pytest.raises(ValueError):
        validate_proof(replace(gs, **{field: value}), network)


@pytest.mark.parametrize("after", [0, 1, 2])
def test_alive_can_precede_ack_or_follow_ack_or_follow_receipt(after):
    from test_gamescript_proof_evidence import MARKERS

    # Three observable interleavings; only each channel's projection is validated.
    timeline = [MARKERS[0], "REQUEST_SENT", MARKERS[1], MARKERS[2]]
    tail = ["NETWORK_ACK_RECEIVED", "RECEIPT_CREATED"]
    tail.insert(after, MARKERS[3])
    timeline += tail
    gs_records = tuple(item for item in timeline if item.startswith("BRIDGE_"))
    gs = parse_gamescript_evidence(native_log(gs_records), REQUEST_ID)
    _, network = channels()
    network = replace(
        network, ordered_sequence=tuple(item for item in timeline if not item.startswith("BRIDGE_"))
    )
    assert validate_proof(gs, network).request_id == REQUEST_ID


def test_ack_payload_and_receipt_must_match():
    gs, network = channels()
    with pytest.raises(ValueError):
        validate_proof(gs, replace(network, response_payload=Ack("wrong").to_bytes()))
    for old, new in [
        (b'"protocol":1', b'"protocol":2'),
        (b'"type":"ack"', b'"type":"other"'),
        (b'"status":"ok"', b'"status":"failed"'),
    ]:
        with pytest.raises(ValueError):
            validate_proof(
                gs, replace(network, response_payload=network.response_payload.replace(old, new))
            )


def test_duplicate_ack_in_later_packet_rejected_without_second_application_request():
    import asyncio
    from unittest.mock import AsyncMock, Mock

    from app.simulation.openttd.admin_protocol import ServerProtocol, encode_admin_frame
    from app.simulation.openttd.gamescript_transport import GameScriptSession, GameScriptTransport
    from app.simulation.openttd.proof.network_evidence import RecordedProofSession

    async def run():
        reader = asyncio.StreamReader()
        writer = Mock(spec=asyncio.StreamWriter)
        writer.drain = AsyncMock()
        writer.wait_closed = AsyncMock()
        sent = []

        def write(frame):
            sent.append(frame[2])
            if frame[2] == 6:
                response = encode_admin_frame(124, Ack(REQUEST_ID).to_bytes() + b"\0")
                reader.feed_data(response)
            elif frame[2] == 7:
                # Duplicate is a subsequent receive, as in the production secure session.
                reader.feed_data(encode_admin_frame(124, Ack(REQUEST_ID).to_bytes() + b"\0"))
                reader.feed_data(encode_admin_frame(126, frame[3:]))

        writer.write.side_effect = write
        session = RecordedProofSession(GameScriptSession(reader, writer), PingRequest(REQUEST_ID))
        transport = GameScriptTransport(session, ServerProtocol(3, ((9, 64),)))
        receipt = await transport.ping(PingRequest(REQUEST_ID))
        with pytest.raises(ValueError, match="Duplicate"):
            await session.finish(receipt)
        assert sent.count(6) == 1

    asyncio.run(run())


def test_raw_gamescript_records_cannot_be_replaced_by_booleans():
    gs, network = channels()
    with pytest.raises(ValueError):
        validate_proof(replace(gs, records=()), network)


@pytest.mark.parametrize(
    "which",
    [
        "openttd-15.3-real-ack-attempt2-prelaunch",
        "openttd-15.3-real-ack-attempt2-prelaunch-gate-failure",
    ],
)
def test_previous_prelaunch_directories_cannot_be_prepared_over(tmp_path, which):
    from test_real_ack_harness import make_prepared

    from app.simulation.openttd.proof.harness import manifest, prepare_proof

    old = tmp_path / which
    old.mkdir()
    (old / "final-report.md").write_text("ATTEMPT #2 NOT EXECUTED — PRELAUNCH GATE FAILED")
    before = manifest(old)
    prepared = make_prepared(tmp_path)
    try:
        with pytest.raises(ValueError, match="immutable"):
            prepare_proof(
                old,
                binary=prepared.spec.identity.executable,
                binary_sha256=prepared.spec.identity.sha256,
            )
        assert manifest(old) == before
    finally:
        prepared.dispose()


def test_obsolete_preparation_rejected_before_any_cleanup_or_write(tmp_path):
    import asyncio
    import json

    from test_real_ack_harness import ControlledBackend, make_prepared

    from app.simulation.openttd.proof.attempt import execute_attempt
    from app.simulation.openttd.proof.harness import manifest
    from app.simulation.openttd.proof.native import load_prepared

    prepared = make_prepared(tmp_path)
    metadata = prepared.directory / "PRELAUNCH.json"
    data = json.loads(metadata.read_text())
    data.pop("proof_model")
    metadata.write_text(json.dumps(data))
    before = manifest(prepared.directory)
    backend = ControlledBackend()
    try:
        with pytest.raises(ValueError, match="v3"):
            asyncio.run(execute_attempt(prepared, backend))
        with pytest.raises(ValueError):
            load_prepared(prepared.directory)
        assert backend.launches == backend.sends == backend.closed == 0
        assert prepared.key_path.is_file()
        assert manifest(prepared.directory) == before
    finally:
        prepared.dispose()


def test_ping_request_identity_and_new_read_only_bridge_package(tmp_path):
    import hashlib
    import json

    from test_real_ack_harness import make_prepared

    prepared = make_prepared(tmp_path)
    try:
        assert prepared.request.request_id == "openttd15-real-ack-002"
        assert (
            hashlib.sha256(prepared.request.to_bytes()).hexdigest()
            == "5abf68c4ad24052e90f00359683828895de8d2b532258d4999165fd3249d907d"
        )
        assert (
            json.loads((prepared.directory / "bridge-package-identity.json").read_text())["sha256"]
            == "b7392d59e44f0b973a1a8bbd6de4ab395df5eb58df79c45cbde33bef7427a783"
        )
    finally:
        prepared.dispose()


def test_recorded_session_second_send_rejected_before_delegate():
    import asyncio
    from unittest.mock import AsyncMock, Mock

    from app.simulation.openttd.gamescript_transport import GameScriptSession, encode_gamescript
    from app.simulation.openttd.proof.network_evidence import RecordedProofSession

    async def run():
        writer = Mock(spec=asyncio.StreamWriter)
        writer.drain = AsyncMock()
        writer.wait_closed = AsyncMock()
        session = RecordedProofSession(
            GameScriptSession(asyncio.StreamReader(), writer), PingRequest(REQUEST_ID)
        )
        packet = encode_gamescript(PingRequest(REQUEST_ID).to_bytes())
        await session.send(packet)
        with pytest.raises(ValueError, match="retry"):
            await session.send(packet)
        assert writer.write.call_count == 1
        assert session.snapshot().retries == 1

    asyncio.run(run())
