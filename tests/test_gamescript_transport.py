"""Admin framing and transport tests using in-memory streams only."""

import struct

import pytest

from app.simulation.openttd.admin_protocol import AdminFrameDecoder
from app.simulation.openttd.gamescript_protocol import PingRequest, handle_ping
from app.simulation.openttd.gamescript_transport import decode_gamescript, encode_gamescript


def test_gamescript_packet_layout_and_fragmented_framing() -> None:
    payload = PingRequest("ack-000001").to_bytes()
    packet = encode_gamescript(payload)
    assert packet == struct.pack("<HB", len(payload) + 4, 6) + payload + b"\0"
    decoder = AdminFrameDecoder()
    assert decoder.feed_frames(packet[:2]) == []
    assert decoder.feed_frames(packet[2:]) == [(6, payload + b"\0")]
    response = handle_ping(decode_gamescript(payload + b"\0"))
    assert decode_gamescript(response + b"\0") == response


def test_controlled_round_trip_and_registration() -> None:
    import asyncio
    from unittest.mock import AsyncMock, Mock

    from app.simulation.openttd.admin_protocol import ServerProtocol
    from app.simulation.openttd.gamescript_transport import GameScriptSession, GameScriptTransport

    async def scenario():
        reader = asyncio.StreamReader()
        writer = Mock(spec=asyncio.StreamWriter)
        writer.drain = AsyncMock()
        writer.wait_closed = AsyncMock()
        writer.is_closing.return_value = False
        packets = []

        def write(frame):
            packets.append(frame)
            if frame[2] == 6:
                response = handle_ping(decode_gamescript(frame[3:]))
                reader.feed_data(struct.pack("<HB", len(response) + 4, 124) + response + b"\0")

        writer.write.side_effect = write
        session = GameScriptSession(reader, writer)
        transport = GameScriptTransport(session, ServerProtocol(3, ((9, 64),)))
        receipt = await transport.ping(PingRequest("ack-000001"), timeout=1)
        assert packets[0] == b"\x07\x00\x02\x09\x00\x40\x00"
        assert receipt.request_id == "ack-000001"
        assert receipt.status == "ok" and receipt.response_type == "ack"
        await session.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "behavior,error_name",
    [
        ("timeout", "TransportTimeout"),
        ("disconnect", "TransportDisconnected"),
        ("bad_json", "MalformedResponse"),
        ("bad_string", "MalformedResponse"),
        ("wrong_id", "TransportProtocolError"),
        ("bad_version", "TransportProtocolError"),
        ("bad_frame", "MalformedResponse"),
        ("partial_eof", "MalformedResponse"),
        ("shutdown", "TransportDisconnected"),
    ],
)
def test_transport_failure_classification(behavior: str, error_name: str) -> None:
    import asyncio
    from unittest.mock import AsyncMock, Mock

    import app.simulation.openttd.gamescript_transport as transport_module
    from app.simulation.openttd.admin_protocol import ServerProtocol
    from app.simulation.openttd.gamescript_protocol import Ack

    async def scenario():
        reader = asyncio.StreamReader()
        writer = Mock(spec=asyncio.StreamWriter)
        writer.drain = AsyncMock()
        writer.wait_closed = AsyncMock()
        writer.is_closing.return_value = False
        if behavior == "disconnect":
            reader.feed_eof()
        elif behavior == "bad_frame":
            reader.feed_data(b"\x02\x00")
        elif behavior == "partial_eof":
            reader.feed_data(b"\x08\x00\x7c{}")
            reader.feed_eof()
        elif behavior == "shutdown":
            reader.feed_data(b"\x03\x00\x6a")
        elif behavior != "timeout":
            body = (
                Ack("other").to_bytes()
                if behavior == "wrong_id"
                else b"{}"
                if behavior == "bad_json"
                else Ack("a").to_bytes().replace(b'"protocol":1', b'"protocol":2')
            )
            body += b"\0" if behavior != "bad_string" else b""
            reader.feed_data(struct.pack("<HB", len(body) + 3, 124) + body)
        session = transport_module.GameScriptSession(reader, writer)
        transport = transport_module.GameScriptTransport(session, ServerProtocol(3, ((9, 64),)))
        with pytest.raises(getattr(transport_module, error_name)):
            await transport.ping(PingRequest("a"), timeout=0.01)
        assert transport.pending_request_id is None
        writer.close.assert_called_once()

    asyncio.run(scenario())


def test_unrelated_packets_ignored_and_pending_request_cannot_be_replaced() -> None:
    import asyncio
    from unittest.mock import AsyncMock, Mock

    from app.simulation.openttd.admin_protocol import ServerProtocol
    from app.simulation.openttd.gamescript_protocol import Ack
    from app.simulation.openttd.gamescript_transport import (
        GameScriptSession,
        GameScriptTransport,
        TransportProtocolError,
    )

    async def scenario():
        reader = asyncio.StreamReader()
        writer = Mock(spec=asyncio.StreamWriter)
        sent = asyncio.Event()
        writer.drain = AsyncMock(side_effect=sent.set)
        writer.wait_closed = AsyncMock()
        session = GameScriptSession(reader, writer)
        transport = GameScriptTransport(session, ServerProtocol(3, ((9, 64),)))
        task = asyncio.create_task(transport.ping(PingRequest("a"), timeout=1))
        await sent.wait()
        assert transport.pending_request_id == "a"
        with pytest.raises(TransportProtocolError, match="pending"):
            await transport.ping(PingRequest("b"), timeout=1)
        reader.feed_data(b"\x03\x00\xfa")
        response = Ack("a").to_bytes()
        reader.feed_data(struct.pack("<HB", len(response) + 4, 124) + response + b"\0")
        assert (await task).request_id == "a"
        assert transport.pending_request_id is None
        with pytest.raises(TransportProtocolError, match="fresh"):
            await transport.ping(PingRequest("a"))
        await session.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("protocol", [(1, ((9, 64),)), (2, ((9, 64),)), (3, ()), (3, ((9, 1),))])
def test_gamescript_automatic_registration_required(protocol) -> None:
    from unittest.mock import Mock

    from app.simulation.openttd.admin_protocol import ServerProtocol
    from app.simulation.openttd.gamescript_transport import (
        GameScriptSession,
        GameScriptTransport,
        TransportProtocolError,
    )

    with pytest.raises(TransportProtocolError):
        GameScriptTransport(Mock(spec=GameScriptSession), ServerProtocol(*protocol))


@pytest.mark.parametrize("body", [b"{}", b"{}\0junk", b"{}\0\0", b"\xff\0", b"x" * 513 + b"\0"])
def test_malformed_server_gamescript_string_rejected(body) -> None:
    from app.simulation.openttd.gamescript_protocol import MalformedMessage

    with pytest.raises(MalformedMessage):
        decode_gamescript(body)


def test_packet_payload_size_boundary() -> None:
    from app.simulation.openttd.gamescript_protocol import MalformedMessage

    request = PingRequest("a").to_bytes()
    assert len(encode_gamescript(request + b" " * (512 - len(request)))) == 516
    with pytest.raises(MalformedMessage):
        encode_gamescript(request + b" " * (513 - len(request)))


def test_subscription_barrier_is_packet_driven_and_precedes_request():
    import asyncio
    from unittest.mock import AsyncMock, Mock

    from app.simulation.openttd.admin_protocol import ServerProtocol, encode_admin_frame
    from app.simulation.openttd.gamescript_transport import GameScriptSession, GameScriptTransport

    async def run():
        reader = asyncio.StreamReader()
        writer = Mock(spec=asyncio.StreamWriter)
        writer.drain = AsyncMock()
        writer.wait_closed = AsyncMock()
        packets = []

        def write(frame):
            packets.append(frame)
            if frame[2] == 7:
                reader.feed_data(encode_admin_frame(126, frame[3:]))

        writer.write.side_effect = write
        transport = GameScriptTransport(
            GameScriptSession(reader, writer), ServerProtocol(3, ((9, 64),))
        )
        await transport.subscribe(token=0x153)
        assert [frame[2] for frame in packets] == [2, 7]
        assert transport.registered

    asyncio.run(run())
