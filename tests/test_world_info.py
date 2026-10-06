import pytest

from app.simulation.openttd.world_info import WorldInfoRequest, WorldInfoResponse


def test_canonical_request_and_response_are_distinct_from_ping():
    request = WorldInfoRequest("world-001")
    assert request.to_bytes() == b'{"protocol":1,"request_id":"world-001","type":"world_info"}'
    response = WorldInfoResponse("world-001", 64, 128)
    assert WorldInfoResponse.parse(response.to_bytes()) == response
    assert WorldInfoRequest.parse(request.to_bytes()) == request
    with pytest.raises(ValueError):
        WorldInfoResponse.parse(
            b'{"protocol":1,"request_id":"world-001","type":"ack","status":"ok"}'
        )


def test_actual_gamescript_reads_fake_map_and_retains_liveness():
    from pathlib import Path

    from squirrel import SQVM

    from app.simulation.openttd.gamescript_bridge import BRIDGE_DIRECTORY

    vm = SQVM()
    vm.execute(Path("tests/fixtures/gamescript_api_15.nut").read_text())
    vm.execute(
        "class GSMap { static function GetMapSizeX() { return 64; } "
        "static function GetMapSizeY() { return 128; } }"
    )
    vm.execute((BRIDGE_DIRECTORY / "main.nut").read_text())
    vm.execute(
        '::events.append(ControlledAdminEvent({protocol=1,type="world_info",'
        'request_id="world-001"})); '
        "::bridge <- NoMutationBridge(); try { bridge.Start(); } "
        'catch(e) { if(e != "CONTROLLED_STOP") throw e; }'
    )
    root = vm.get_roottable()
    assert len(root["replies"]) == 1
    assert int(root["replies"][0]["map_width"]) == 64
    assert int(root["replies"][0]["map_height"]) == 128
    assert [str(m) for m in root["markers"]] == [
        "BRIDGE_STARTED protocol=1 api=15",
        "BRIDGE_REQUEST_RECEIVED request_id=world-001 type=world_info protocol=1",
        "WORLD_INFO_READ request_id=world-001 map_width=64 map_height=128",
        "BRIDGE_RESPONSE_SENT request_id=world-001 type=world_info_result status=ok protocol=1",
        "BRIDGE_POST_RESPONSE_ALIVE request_id=world-001",
    ]
    assert root["ticks"] == 2


def test_internal_evidence_is_required_for_independent_verification():
    from app.simulation.openttd.world_info_evidence import parse_world_info_evidence

    response = WorldInfoResponse("world-001", 64, 128)
    raw = b"dbg: [script:4] [18] [I] BRIDGE_STARTED protocol=1 api=15\n"
    evidence = parse_world_info_evidence(raw, "world-001")
    with pytest.raises(ValueError):
        evidence.require_complete(response)


def test_world_info_transport_rejects_ping_ack():
    import asyncio
    from unittest.mock import AsyncMock, Mock

    from app.simulation.openttd.admin_protocol import ServerProtocol, encode_admin_frame
    from app.simulation.openttd.gamescript_protocol import Ack
    from app.simulation.openttd.gamescript_transport import (
        GameScriptSession,
        GameScriptTransport,
        TransportProtocolError,
    )

    async def scenario():
        reader = asyncio.StreamReader()
        writer = Mock(spec=asyncio.StreamWriter)
        writer.drain = AsyncMock()
        writer.wait_closed = AsyncMock()

        def write(frame):
            if frame[2] == 7:
                reader.feed_data(encode_admin_frame(126, frame[3:]))
            elif frame[2] == 6:
                reader.feed_data(encode_admin_frame(124, Ack("world-001").to_bytes() + b"\0"))

        writer.write.side_effect = write
        transport = GameScriptTransport(
            GameScriptSession(reader, writer), ServerProtocol(3, ((9, 64),))
        )
        with pytest.raises(TransportProtocolError):
            await transport.world_info(WorldInfoRequest("world-001"), timeout=1)

    asyncio.run(scenario())


def _world_round_trip(*, gs_dimensions=(64, 128), admin_dimensions=(64, 128), behavior="ok"):
    """Independent fake channels; actual current Squirrel Start and packet encoder."""
    import asyncio
    import json
    import struct
    from pathlib import Path
    from unittest.mock import AsyncMock, Mock

    from squirrel import SQVM

    from app.simulation.openttd.admin_protocol import (
        ServerProtocol,
        ServerWelcome,
        decode_server_packet,
        encode_admin_frame,
    )
    from app.simulation.openttd.gamescript_bridge import BRIDGE_DIRECTORY, BridgePackage
    from app.simulation.openttd.gamescript_transport import (
        GameScriptSession,
        GameScriptTransport,
        decode_gamescript,
    )
    from app.simulation.openttd.runtime.identity import RuntimeIdentity
    from app.simulation.openttd.world_info import verify_world_info
    from app.simulation.openttd.world_info_evidence import parse_world_info_evidence

    async def scenario():
        reader = asyncio.StreamReader()
        writer = Mock(spec=asyncio.StreamWriter)
        writer.drain = AsyncMock()
        writer.wait_closed = AsyncMock()
        packets = []
        vm = SQVM()
        vm.execute(Path("tests/fixtures/gamescript_api_15.nut").read_text())
        vm.execute(
            "class GSMap { static function GetMapSizeX() { return "
            + str(gs_dimensions[0])
            + "; } static function GetMapSizeY() { return "
            + str(gs_dimensions[1])
            + "; } }"
        )
        vm.execute((BRIDGE_DIRECTORY / "main.nut").read_text())

        def write(frame):
            packets.append(frame)
            if frame[2] == 7:
                reader.feed_data(encode_admin_frame(126, frame[3:]))
                return
            if frame[2] != 6:
                return
            query = json.loads(decode_gamescript(frame[3:]))
            # Values came from the actual encoded Python packet, not a second fixture request.
            vm.execute(
                "::events.append(ControlledAdminEvent({protocol="
                + str(query["protocol"])
                + ',type="'
                + query["type"]
                + '",request_id="'
                + query["request_id"]
                + '"})); ::bridge <- NoMutationBridge(); try { bridge.Start(); } '
                'catch(e) { if(e != "CONTROLLED_STOP") throw e; }'
            )
            table = vm.get_roottable()["replies"][0]
            obj = {
                k: (
                    int(table[k]) if k in ("protocol", "map_width", "map_height") else str(table[k])
                )
                for k in ("protocol", "type", "request_id", "status", "map_width", "map_height")
            }
            if behavior == "wrong_id":
                obj["request_id"] = "different"
            if behavior == "ping_ack":
                obj = {
                    "protocol": 1,
                    "type": "ack",
                    "request_id": query["request_id"],
                    "status": "ok",
                }
            if behavior == "malformed":
                obj["map_width"] = 0
            response = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
            if behavior == "timeout":
                return
            if behavior == "disconnect":
                reader.feed_eof()
                return
            reader.feed_data(encode_admin_frame(107, struct.pack("<I", 712224)))
            reader.feed_data(encode_admin_frame(124, response + b"\0"))
            if behavior == "duplicate":
                reader.feed_data(encode_admin_frame(124, response + b"\0"))

        writer.write.side_effect = write
        transport = GameScriptTransport(
            GameScriptSession(reader, writer), ServerProtocol(3, ((9, 64),))
        )
        exchange = await transport.world_info(WorldInfoRequest("world-001"), timeout=0.1)
        raw = "".join(
            "dbg: [script:4] [18] [I] " + str(m) + "\n" for m in vm.get_roottable()["markers"]
        ).encode()
        evidence = parse_world_info_evidence(raw, "world-001", source_log="controlled.log")
        # Separate Admin packet fixture, with independently supplied dimensions.
        welcome = decode_server_packet(
            104,
            b"Server\0" + b"15.3\0\x01\0" + struct.pack("<IBIHH", 42, 0, 712223, *admin_dimensions),
        )
        assert isinstance(welcome, ServerWelcome)
        runtime = RuntimeIdentity(Path("/controlled/openttd"), "15.3", "a" * 64)
        bridge = BridgePackage(BRIDGE_DIRECTORY, "b" * 64)
        verified = verify_world_info(exchange, evidence, welcome, runtime=runtime, bridge=bridge)
        assert sum(frame[2] == 6 for frame in packets) == 1
        with pytest.raises(ValueError):
            await transport.world_info(WorldInfoRequest("world-001"))
        await transport.session.close()
        return exchange, evidence, welcome, verified, runtime, bridge

    return asyncio.run(scenario())


@pytest.mark.parametrize(
    "admin_dimensions,match",
    [((64, 128), True), ((128, 128), False), ((64, 256), False), ((128, 256), False)],
)
def test_full_packet_squirrel_independent_verification(admin_dimensions, match):
    exchange, evidence, welcome, result, runtime, bridge = _world_round_trip(
        admin_dimensions=admin_dimensions
    )
    assert result.dimensions_match is match
    assert result.reported_dimensions == (64, 128)
    assert result.independently_observed_dimensions == admin_dimensions
    if not match:
        with pytest.raises(ValueError):
            result.require_match()
    from app.simulation.openttd.world_info import verify_world_info

    assert verify_world_info(exchange, evidence, welcome, runtime=runtime, bridge=bridge) == result


@pytest.mark.parametrize(
    "behavior,exception",
    [
        ("wrong_id", "TransportProtocolError"),
        ("ping_ack", "TransportProtocolError"),
        ("malformed", "MalformedResponse"),
        ("duplicate", "TransportProtocolError"),
        ("timeout", "TransportTimeout"),
        ("disconnect", "TransportDisconnected"),
    ],
)
def test_world_transport_failures_distinct_and_never_retry(behavior, exception):
    import app.simulation.openttd.gamescript_transport as transport

    with pytest.raises(getattr(transport, exception)):
        _world_round_trip(behavior=behavior)


@pytest.mark.parametrize(
    "field,value",
    [
        ("map_width", 0),
        ("map_height", -1),
        ("map_width", True),
        ("map_height", 1.0),
        ("map_width", 65),
        ("map_height", 65536),
    ],
)
def test_invalid_dimensions_rejected(field, value):
    import json

    obj = json.loads(WorldInfoResponse("world-001", 64, 128).to_bytes())
    obj[field] = value
    with pytest.raises(ValueError):
        WorldInfoResponse.parse(json.dumps(obj).encode())


@pytest.mark.parametrize("parser", [WorldInfoRequest.parse, WorldInfoResponse.parse])
def test_payload_size_and_duplicate_keys_are_strict(parser):
    with pytest.raises(ValueError):
        parser(b" " * 513)
    with pytest.raises(ValueError):
        parser(b'{"protocol":1,"protocol":1}')


def test_safe_id_and_canonical_response_size():
    import hashlib

    for bad in ("", "_a", "x" * 65, "space id", "nonascii-\u00e9"):
        with pytest.raises(ValueError):
            WorldInfoRequest(bad)
    assert len(WorldInfoRequest("a" * 64).to_bytes()) < 512
    response = WorldInfoResponse("a" * 64, 32768, 32768).to_bytes()
    assert len(response) == 172 < 512 < 1450
    assert (
        hashlib.sha256(response).digest()
        == hashlib.sha256(WorldInfoResponse("a" * 64, 32768, 32768).to_bytes()).digest()
    )


@pytest.mark.parametrize(
    "change",
    [{"protocol": 2}, {"protocol": True}, {"type": "unknown"}, {"status": "failed"}, {"extra": 1}],
)
def test_response_unknown_fields_types_and_protocol_rejected(change):
    import json

    value = json.loads(WorldInfoResponse("world-001", 64, 128).to_bytes())
    value.update(change)
    with pytest.raises(ValueError):
        WorldInfoResponse.parse(json.dumps(value).encode())


@pytest.mark.parametrize(
    "missing",
    ["WORLD_INFO_READ", "BRIDGE_RESPONSE_SENT", "BRIDGE_POST_RESPONSE_ALIVE", "BRIDGE_STARTED"],
)
def test_missing_internal_evidence_cannot_verify(missing):
    from app.simulation.openttd.world_info_evidence import parse_world_info_evidence

    _, evidence, _, _, _, _ = _world_round_trip()
    raw = b"".join(
        line for line in evidence.raw_log.splitlines(keepends=True) if missing.encode() not in line
    )
    with pytest.raises(ValueError):
        candidate = parse_world_info_evidence(raw, "world-001")
        candidate.require_complete(WorldInfoResponse("world-001", 64, 128))


@pytest.mark.parametrize(
    "sequence",
    [
        (
            "BRIDGE_REQUEST_RECEIVED",
            "WORLD_INFO_READ",
            "BRIDGE_POST_RESPONSE_ALIVE",
            "BRIDGE_RESPONSE_SENT",
        ),
        (
            "WORLD_INFO_READ",
            "BRIDGE_REQUEST_RECEIVED",
            "BRIDGE_RESPONSE_SENT",
            "BRIDGE_POST_RESPONSE_ALIVE",
        ),
    ],
)
def test_invalid_internal_order_rejected(sequence):
    from app.simulation.openttd.world_info_evidence import parse_world_info_evidence

    _, evidence, _, _, _, _ = _world_round_trip()
    lines = {r.marker: r.raw_line for r in evidence.records}
    raw = ("\n".join([lines["BRIDGE_STARTED"]] + [lines[n] for n in sequence]) + "\n").encode()
    with pytest.raises(ValueError):
        parse_world_info_evidence(raw, "world-001")


def test_world_response_cannot_satisfy_ping_and_old_receipt():
    from app.simulation.openttd.gamescript_protocol import Ack, CommunicationReceipt, PingRequest

    with pytest.raises(ValueError):
        Ack.parse(WorldInfoResponse("world-001", 64, 128).to_bytes())
    with pytest.raises(ValueError):
        CommunicationReceipt.correlate(
            PingRequest("world-001").to_bytes(), WorldInfoResponse("world-001", 64, 128).to_bytes()
        )


def test_world_proof_requires_network_receipt_and_both_chains():
    from dataclasses import replace

    from app.simulation.openttd.world_info import verify_world_info

    exchange, evidence, welcome, _, runtime, bridge = _world_round_trip()
    for altered in (
        replace(exchange, response_payload=b""),
        replace(exchange, requests_sent=2),
        replace(exchange, matching_responses=2),
        replace(exchange, retries=1),
        replace(exchange, ordered_sequence=tuple(reversed(exchange.ordered_sequence))),
    ):
        with pytest.raises(ValueError):
            verify_world_info(altered, evidence, welcome, runtime=runtime, bridge=bridge)


def test_verified_15_3_game_api_names_and_read_only_implementation():
    import hashlib
    import json
    import re
    from pathlib import Path

    from app.simulation.openttd.gamescript_bridge import BRIDGE_DIRECTORY

    reference = Path("tests/reference/world_info_15_3")
    manifest = json.loads((reference / "manifest.json").read_text())
    assert manifest["version"] == "15.3"
    for name, identity in manifest["files"].items():
        assert hashlib.sha256((reference / name).read_bytes()).hexdigest() == identity["sha256"]
    header = (reference / "script_map.hpp").read_text()
    implementation = (reference / "script_map.cpp").read_text()
    binding = (reference / "api-CMakeLists.txt").read_text()
    network = (reference / "network_admin.cpp").read_text()
    assert "@api ai game" in header and '"game;GS"' in binding
    for axis in ("X", "Y"):
        assert f"static SQInteger GetMapSize{axis}();" in header
        assert re.search(
            rf"ScriptMap::GetMapSize{axis}\(\)\s*{{\s*return ::Map::Size{axis}\(\);\s*}}",
            implementation,
        )
        assert f"p->Send_uint16(Map::Size{axis}());" in network
    source = (BRIDGE_DIRECTORY / "main.nut").read_text()
    assert set(re.findall(r"GSMap\.([A-Za-z]+)\(", source)) == {
        "GetMapSizeX",
        "GetMapSizeY",
        "GetTileX",
        "GetTileY",
        "IsValidTile",
    }
    assert set(re.findall(r"\bGS[A-Za-z0-9_]+\b", source)) == {
        "GSMap",
        "GSList",
        "GSIndustryList",
        "GSIndustry",
        "GSController",
        "GSLog",
        "GSAdmin",
        "GSEventController",
        "GSEvent",
        "GSEventAdminPort",
    }
    assert all(
        symbol not in source
        for symbol in (
            "GSCompanyMode",
            "GSTestMode",
            "GSRoad",
            "GSRail",
            "GSStation",
            "GSVehicle",
            "GSOrder",
            "GSTile",
            "GSCompany",
            "RCON",
            "Save(",
            "Load(",
        )
    )


def test_world_send_failure_has_no_response_sent_or_liveness_marker():
    from pathlib import Path

    from squirrel import SQVM

    from app.simulation.openttd.gamescript_bridge import BRIDGE_DIRECTORY

    vm = SQVM()
    vm.execute(Path("tests/fixtures/gamescript_api_15.nut").read_text())
    vm.execute(
        "::send_ok=false; class GSMap { static function GetMapSizeX() { return 64; } "
        "static function GetMapSizeY() { return 128; } }"
    )
    vm.execute((BRIDGE_DIRECTORY / "main.nut").read_text())
    vm.execute(
        '::events.append(ControlledAdminEvent({protocol=1,type="world_info",'
        'request_id="world-001"})); '
        "::bridge <- NoMutationBridge(); try { bridge.Start(); } "
        'catch(e) { if(e != "CONTROLLED_STOP") throw e; }'
    )
    markers = [str(m) for m in vm.get_roottable()["markers"]]
    assert any("WORLD_INFO_READ" in m for m in markers)
    assert not any(
        "BRIDGE_RESPONSE_SENT" in m or "BRIDGE_POST_RESPONSE_ALIVE" in m for m in markers
    )
    assert len(vm.get_roottable()["replies"]) == 0


@pytest.mark.parametrize("kind", ["world_info", "ping"])
def test_session_accepts_only_known_commands(kind):
    import asyncio
    from unittest.mock import Mock

    from app.simulation.openttd.gamescript_protocol import PingRequest
    from app.simulation.openttd.gamescript_transport import GameScriptSession, encode_gamescript

    loop = asyncio.new_event_loop()
    session = GameScriptSession(asyncio.StreamReader(loop=loop), Mock())
    request = WorldInfoRequest("world-001") if kind == "world_info" else PingRequest("world-001")
    session.validate_outbound(encode_gamescript(request.to_bytes()))
    with pytest.raises(ValueError):
        session.validate_outbound(
            encode_gamescript(b'{"protocol":1,"request_id":"world-001","type":"build"}')
        )
    loop.close()


def test_raw_records_digest_and_wrong_identity_are_not_booleans_only():
    import hashlib
    from dataclasses import replace

    from app.simulation.openttd.world_info_evidence import parse_world_info_evidence

    exchange, evidence, _, _, _, _ = _world_round_trip()
    assert evidence.raw_evidence_digest == hashlib.sha256(evidence.raw_log).hexdigest()
    assert evidence.records[2].marker == "WORLD_INFO_READ"
    assert evidence.records[2].raw_line in evidence.raw_log.decode()
    assert (
        parse_world_info_evidence(evidence.raw_log, "world-001") != evidence
    )  # source_log differs
    for forged in (
        replace(evidence, raw_evidence_digest="0" * 64),
        replace(evidence, records=tuple()),
        replace(evidence, dimensions_read=(128, 128)),
    ):
        with pytest.raises(ValueError):
            forged.require_complete(exchange.response)
    with pytest.raises(ValueError):
        parse_world_info_evidence(evidence.raw_log, "wrong-001")
    with pytest.raises(ValueError):
        parse_world_info_evidence(evidence.raw_log.replace(b"[18]", b"[0]"), "world-001")


def test_ping_cannot_be_used_as_world_info_request():
    from app.simulation.openttd.gamescript_protocol import PingRequest

    with pytest.raises(ValueError):
        WorldInfoRequest.parse(PingRequest("world-001").to_bytes())


def test_network_dimensions_cannot_replace_internal_read_values():
    from dataclasses import replace

    from app.simulation.openttd.world_info import WorldInfoReceipt, verify_world_info

    exchange, evidence, welcome, _, runtime, bridge = _world_round_trip()
    payload = WorldInfoResponse("world-001", 128, 128).to_bytes()
    altered = replace(
        exchange,
        response_payload=payload,
        receipt=WorldInfoReceipt.correlate(exchange.request_payload, payload),
    )
    with pytest.raises(ValueError):
        verify_world_info(
            altered, evidence, replace(welcome, width=128), runtime=runtime, bridge=bridge
        )


def test_duplicate_response_in_later_read_is_rejected():
    import asyncio
    from unittest.mock import AsyncMock, Mock

    from app.simulation.openttd.admin_protocol import ServerProtocol, encode_admin_frame
    from app.simulation.openttd.gamescript_transport import (
        GameScriptSession,
        GameScriptTransport,
        TransportProtocolError,
    )

    async def scenario():
        reader = asyncio.StreamReader()
        writer = Mock(spec=asyncio.StreamWriter)
        writer.drain = AsyncMock()
        writer.wait_closed = AsyncMock()
        response = encode_admin_frame(
            124, WorldInfoResponse("world-001", 64, 128).to_bytes() + b"\0"
        )
        requests = []

        def write(frame):
            if frame[2] == 6:
                requests.append(frame)
                reader.feed_data(response)
            elif frame[2] == 7:
                if frame[3:] == b"\x54\x01\x00\x00":
                    reader.feed_data(response)
                reader.feed_data(encode_admin_frame(126, frame[3:]))

        writer.write.side_effect = write
        transport = GameScriptTransport(
            GameScriptSession(reader, writer), ServerProtocol(3, ((9, 64),))
        )
        with pytest.raises(TransportProtocolError):
            await transport.world_info(WorldInfoRequest("world-001"), timeout=1)
        assert len(requests) == 1

    asyncio.run(scenario())


def test_world_response_cannot_satisfy_ping_transport():
    import asyncio
    from unittest.mock import AsyncMock, Mock

    from app.simulation.openttd.admin_protocol import ServerProtocol, encode_admin_frame
    from app.simulation.openttd.gamescript_protocol import PingRequest
    from app.simulation.openttd.gamescript_transport import (
        GameScriptSession,
        GameScriptTransport,
        TransportProtocolError,
    )

    async def scenario():
        reader = asyncio.StreamReader()
        writer = Mock(spec=asyncio.StreamWriter)
        writer.drain = AsyncMock()
        writer.wait_closed = AsyncMock()

        def write(frame):
            if frame[2] == 6:
                reader.feed_data(
                    encode_admin_frame(
                        124, WorldInfoResponse("world-001", 64, 128).to_bytes() + b"\0"
                    )
                )

        writer.write.side_effect = write
        transport = GameScriptTransport(
            GameScriptSession(reader, writer), ServerProtocol(3, ((9, 64),))
        )
        with pytest.raises(TransportProtocolError):
            await transport.ping(PingRequest("world-001"), timeout=1)

    asyncio.run(scenario())
