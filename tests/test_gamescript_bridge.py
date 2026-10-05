"""Actual no-mutation Squirrel bridge, with verified 15.3 API-shaped fakes."""

import re
from pathlib import Path

import pytest
from squirrel import SQVM

from app.simulation.openttd.gamescript_bridge import BRIDGE_DIRECTORY


def test_actual_bridge_handler_echoes_duplicate_ping_and_rejects_invalid() -> None:
    vm = SQVM()
    vm.execute(
        "class GSController {} class GSLog { static function Info(value) {} } "
        "class GSAdmin { static function Send(value) {"
        " ::replies.append(value); return true; } } ::replies <- [];"
    )
    vm.execute((BRIDGE_DIRECTORY / "main.nut").read_text())
    vm.execute(
        "::bridge <- NoMutationBridge(); "
        'local request = {protocol=1,type="ping",request_id="ack-000001"}; '
        "bridge.Handle(request); bridge.Handle(request); "
        'bridge.Handle({protocol=2,type="ping",request_id="wrong"});'
    )
    replies = vm.get_roottable()["replies"]
    assert len(replies) == 2
    assert str(replies[0]["request_id"]) == "ack-000001"
    assert str(replies[1]["request_id"]) == "ack-000001"
    assert str(replies[0]["status"]) == "ok"


def test_start_handles_admin_events_and_stays_alive() -> None:
    vm = SQVM()
    vm.execute(Path("tests/fixtures/gamescript_api_15.nut").read_text())
    vm.execute((BRIDGE_DIRECTORY / "main.nut").read_text())
    vm.execute("""
        ::events.append(ControlledAdminEvent({protocol=1,type="ping",request_id="ack-000001"}));
        ::bridge <- NoMutationBridge();
        try { bridge.Start(); } catch(e) { if (e != "CONTROLLED_STOP") throw e; }
    """)
    root = vm.get_roottable()
    assert len(root["replies"]) == 1
    assert root["ticks"] == 2
    assert str(root["replies"][0]["request_id"]) == "ack-000001"


def test_package_stages_into_runtime_and_selects_api_15(tmp_path) -> None:
    from app.simulation.openttd.gamescript_bridge import stage_bridge
    from app.simulation.openttd.runtime.config import AdminSettings, RuntimeWorkspace

    workspace = RuntimeWorkspace.create(tmp_path)
    try:
        workspace.write_config(AdminSettings(password="proof"))
        package = stage_bridge(workspace)
        assert package.directory == workspace.game / "NoMutationBridge"
        assert (package.directory / "main.nut").read_bytes() == (
            BRIDGE_DIRECTORY / "main.nut"
        ).read_bytes()
        assert "[game_scripts]\nNoMutationBridge = \n" in workspace.config.read_text()
        assert len(package.sha256) == 64
        assert 'return "15";' in (package.directory / "info.nut").read_text()
    finally:
        workspace.close()


@pytest.mark.parametrize(
    "squirrel_request",
    [
        "null",
        "{}",
        '{protocol=2,type="ping",request_id="a"}',
        '{protocol=true,type="ping",request_id="a"}',
        '{protocol=1.0,type="ping",request_id="a"}',
        '{protocol=1,type="build",request_id="a"}',
        '{protocol=1,type="ping"}',
        '{protocol=1,type="ping",request_id=""}',
        '{protocol=1,type="ping",request_id="_a"}',
        '{protocol=1,type="ping",request_id="a b"}',
        '{protocol=1,type="ping",request_id="' + ("a" * 65) + '"}',
        '{protocol=1,type="ping",request_id="a",extra=1}',
    ],
)
def test_actual_bridge_rejects_malformed_objects(squirrel_request) -> None:
    vm = SQVM()
    vm.execute(Path("tests/fixtures/gamescript_api_15.nut").read_text())
    vm.execute((BRIDGE_DIRECTORY / "main.nut").read_text())
    vm.execute("::bridge <- NoMutationBridge(); bridge.Handle(" + squirrel_request + ");")
    assert len(vm.get_roottable()["replies"]) == 0


def test_bridge_symbols_are_minimal_and_api_version_is_15() -> None:
    source = (BRIDGE_DIRECTORY / "main.nut").read_text()
    info = (BRIDGE_DIRECTORY / "info.nut").read_text()
    assert set(re.findall(r"\bGS[A-Za-z0-9_]+\b", source)) == {
        "GSController",
        "GSAdmin",
        "GSLog",
        "GSMap",
        "GSEventController",
        "GSEvent",
        "GSEventAdminPort",
    }
    assert "GSAdmin.Send(ack)" in source
    assert "GSEvent.ET_ADMIN_PORT" in source
    assert "GSEventAdminPort.Convert(event)" in source and "message.GetObject()" in source
    vm = SQVM()
    vm.execute("class GSInfo {} function RegisterGS(info) { ::registered <- info; }")
    vm.execute(info)
    vm.execute("::api <- registered.GetAPIVersion();")
    assert str(vm.get_roottable()["api"]) == "15"


def test_actual_squirrel_maximum_id_ack_is_bounded() -> None:
    import json

    vm = SQVM()
    vm.execute(Path("tests/fixtures/gamescript_api_15.nut").read_text())
    vm.execute((BRIDGE_DIRECTORY / "main.nut").read_text())
    vm.execute(
        '::bridge <- NoMutationBridge(); bridge.Handle({protocol=1,type="ping",request_id="'
        + ("a" * 64)
        + '"});'
    )
    table = vm.get_roottable()["replies"][0]
    encoded = json.dumps(
        {
            "protocol": int(table["protocol"]),
            "type": str(table["type"]),
            "request_id": str(table["request_id"]),
            "status": str(table["status"]),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    assert len(encoded) == 121 < 1450


def test_controlled_round_trip_through_actual_squirrel_start() -> None:
    import asyncio
    import json
    import struct
    from unittest.mock import AsyncMock, Mock

    from app.simulation.openttd.admin_protocol import ServerProtocol
    from app.simulation.openttd.gamescript_protocol import PingRequest
    from app.simulation.openttd.gamescript_transport import (
        GameScriptSession,
        GameScriptTransport,
        decode_gamescript,
    )

    async def scenario():
        reader = asyncio.StreamReader()
        writer = Mock(spec=asyncio.StreamWriter)
        writer.drain = AsyncMock()
        writer.wait_closed = AsyncMock()
        vm = SQVM()
        vm.execute(Path("tests/fixtures/gamescript_api_15.nut").read_text())
        vm.execute((BRIDGE_DIRECTORY / "main.nut").read_text())

        def write(packet):
            if packet[2] != 6:
                return
            incoming = json.loads(decode_gamescript(packet[3:]))
            vm.execute(
                "::events.append(ControlledAdminEvent({protocol="
                + str(incoming["protocol"])
                + ",type="
                + json.dumps(incoming["type"])
                + ",request_id="
                + json.dumps(incoming["request_id"])
                + "}));"
            )
            vm.execute(
                "::bridge <- NoMutationBridge(); try { bridge.Start(); } "
                'catch(e) { if (e != "CONTROLLED_STOP") throw e; }'
            )
            table = vm.get_roottable()["replies"][0]
            response = json.dumps(
                {
                    "protocol": int(table["protocol"]),
                    "type": str(table["type"]),
                    "request_id": str(table["request_id"]),
                    "status": str(table["status"]),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            reader.feed_data(struct.pack("<HB", len(response) + 4, 124) + response + b"\0")

        writer.write.side_effect = write
        session = GameScriptSession(reader, writer)
        transport = GameScriptTransport(session, ServerProtocol(3, ((9, 64),)))
        receipt = await transport.ping(PingRequest("ack-000001"), timeout=1)
        assert receipt.request_id == "ack-000001" and receipt.status == "ok"
        assert vm.get_roottable()["ticks"] == 2
        await session.close()

    asyncio.run(scenario())
