"""Source-derived OpenTTD 13.4 wire fixtures; no captured packet bytes are claimed."""

import ast
import struct
from datetime import date
from pathlib import Path

import pytest

from app.simulation.openttd.admin_protocol import (
    AdminFrameDecoder,
    AdminFrequency,
    AdminProtocolError,
    AdminUpdateType,
    CompanyNew,
    CompanyRemove,
    CompanyUpdate,
    ServerBanned,
    ServerError,
    ServerFull,
    ServerNewGame,
    ServerPong,
    ServerProtocol,
    ServerShutdown,
    ServerWelcome,
    UnknownPacket,
    decode_server_packet,
    encode_admin_join,
    encode_admin_ping,
    encode_admin_poll,
    encode_admin_quit,
    encode_admin_update_frequency,
)
from app.simulation.openttd.telemetry import (
    CompanyEconomyObservation,
    CompanyInfoObservation,
    CompanyStatsObservation,
    GameDateObservation,
    supported_game_day_to_date,
)


def test_company_economy_preserves_signed_money_and_completed_quarters() -> None:
    # Synthesized from network_admin.cpp::SendCompanyEconomy at tag 13.4.
    payload = struct.pack(
        "<BqqqHqHHqHH",
        0,
        -50,
        100_000,
        -2_500,
        65_535,
        500_000,
        100,
        42,
        400_000,
        80,
        0,
    )

    economy = decode_server_packet(117, payload)

    assert isinstance(economy, CompanyEconomyObservation)
    assert economy.cash_balance_gbp == -50
    assert economy.loan_balance_gbp == 100_000
    assert economy.admin_year_to_date_net_income_gbp == -2_500
    assert economy.current_quarter_delivered_cargo_capped == 65_535
    assert economy.current_quarter_cargo_may_be_saturated
    assert [
        (
            quarter.history_offset,
            quarter.company_value_gbp,
            quarter.performance_score,
            quarter.delivered_cargo_capped,
        )
        for quarter in economy.completed_quarters
    ] == [
        (1, 500_000, 100, 42),
        (2, 400_000, 80, 0),
    ]


def test_handshake_and_required_update_masks() -> None:
    # Synthesized from tcp_admin.h and network_admin.cpp::SendProtocol/SendWelcome.
    protocol_payload = (
        b"\x02"
        + b"".join(
            struct.pack("<BHH", 1, update_type, mask)
            for update_type, mask in ((0, 63), (2, 65), (3, 61), (4, 61))
        )
        + b"\x00"
    )
    protocol = decode_server_packet(103, protocol_payload)
    assert isinstance(protocol, ServerProtocol)
    assert protocol.version == 2
    assert protocol.frequencies == {0: 63, 2: 65, 3: 61, 4: 61}
    assert protocol.supports(AdminUpdateType.DATE, AdminFrequency.DAILY)
    assert protocol.supports(AdminUpdateType.COMPANY_INFO, AdminFrequency.AUTOMATIC)
    assert protocol.supports(AdminUpdateType.COMPANY_ECONOMY, AdminFrequency.MONTHLY)
    assert not protocol.supports(AdminUpdateType.COMPANY_INFO, AdminFrequency.MONTHLY)

    welcome_payload = b"Server\0" + b"13.4\0\x01\0" + struct.pack("<IBIHH", 17, 0, 712223, 256, 256)
    welcome = decode_server_packet(104, welcome_payload)
    assert isinstance(welcome, ServerWelcome)
    assert (welcome.name, welcome.revision, welcome.dedicated) == ("Server", "13.4", True)
    assert (welcome.map_name, welcome.seed, welcome.landscape) == ("", 17, 0)
    assert (welcome.start_day, welcome.width, welcome.height) == (712223, 256, 256)


def test_date_company_info_and_stats_preserve_wire_categories() -> None:
    game_date = decode_server_packet(107, struct.pack("<I", 712223))
    assert isinstance(game_date, GameDateObservation)
    assert game_date.calendar_date == date(1950, 1, 1)

    info_payload = b"\x00Road Co\0Manager\0" + struct.pack(
        "<BBIBB4B", 3, 2, 1950, 1, 0, 255, 255, 255, 255
    )
    info = decode_server_packet(114, info_payload)
    assert isinstance(info, CompanyInfoObservation)
    assert (info.company_id, info.name, info.manager, info.colour) == (0, "Road Co", "Manager", 3)
    assert info.password_protected is True  # OpenTTD bool means nonzero, not only 1.
    assert (info.inaugurated_year, info.is_ai, info.bankruptcy_quarters) == (1950, True, 0)
    assert info.share_owners == (255, 255, 255, 255)

    stats = decode_server_packet(118, struct.pack("<B10H", 0, *range(1, 11)))
    assert isinstance(stats, CompanyStatsObservation)
    assert stats.primary_vehicles.model_dump() == {
        "train": 1,
        "lorry": 2,
        "bus": 3,
        "plane": 4,
        "ship": 5,
    }
    assert stats.station_facilities.model_dump() == {
        "train_station": 6,
        "lorry_station": 7,
        "bus_stop": 8,
        "airport_or_heliport": 9,
        "harbour": 10,
    }
    assert "wagon_count" not in stats.model_dump_json()
    assert "capacity" not in stats.model_dump_json()
    assert "route" not in stats.model_dump_json()


@pytest.mark.parametrize("day", [0, 365, 3652425, 2**32 - 1])
def test_unsupported_game_day_rejected(day: int) -> None:
    with pytest.raises(ValueError, match="supported"):
        supported_game_day_to_date(day)


def test_year_zero_offset_and_last_supported_day() -> None:
    assert supported_game_day_to_date(366) == date(1, 1, 1)
    assert supported_game_day_to_date(3652424) == date(9999, 12, 31)


def _frame(packet_id: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HB", len(payload) + 3, packet_id) + payload


def test_fragmented_and_coalesced_frames_preserve_order_and_unknown_ids() -> None:
    decoder = AdminFrameDecoder()
    wire = _frame(107, struct.pack("<I", 712223)) + _frame(250, b"opaque")
    assert decoder.feed(wire[:1]) == []
    assert decoder.feed(wire[1:5]) == []
    packets = decoder.feed(wire[5:])
    assert isinstance(packets[0], GameDateObservation)
    assert packets[0].game_day == 712223
    assert packets[1] == UnknownPacket(packet_id=250, payload_length=6)
    assert decoder.finish() is None


def test_known_trailing_data_is_ignored_but_malformed_known_packet_fails() -> None:
    assert decode_server_packet(107, struct.pack("<I", 712223) + b"future") == GameDateObservation(
        game_day=712223
    )
    with pytest.raises(AdminProtocolError, match="truncated"):
        decode_server_packet(107, b"\x01\x02\x03")
    with pytest.raises(AdminProtocolError, match="unterminated"):
        decode_server_packet(114, b"\x00missing terminator")
    with pytest.raises(AdminProtocolError, match="UTF-8"):
        decode_server_packet(114, b"\x00\xff\0")
    with pytest.raises(AdminProtocolError, match="length"):
        decode_server_packet(114, b"\x00" + b"a" * 1025 + b"\0")
    with pytest.raises(AdminProtocolError, match="truncated"):
        decode_server_packet(103, b"\x02\x01\x00")
    economy = struct.pack("<BqqqHqHHqHH", 0, -50, 100_000, -2_500, 0, 0, 0, 0, 0, 0, 0)
    with pytest.raises(AdminProtocolError, match="truncated"):
        decode_server_packet(117, economy[:-1])
    with pytest.raises(ValueError, match="supported"):
        decode_server_packet(107, struct.pack("<I", 0))


@pytest.mark.parametrize("length", [0, 2, 32768, 65535])
def test_invalid_frame_length_is_rejected_before_body_allocation(length: int) -> None:
    with pytest.raises(AdminProtocolError, match="frame length"):
        AdminFrameDecoder().feed(struct.pack("<H", length))


def test_eof_distinguishes_clean_completion_from_truncation() -> None:
    clean = AdminFrameDecoder()
    assert clean.feed(_frame(107, struct.pack("<I", 712223)))
    clean.finish()
    with pytest.raises(AdminProtocolError, match="closed"):
        clean.feed(b"x")

    for partial in (b"\x07", _frame(107, struct.pack("<I", 712223))[:-1]):
        decoder = AdminFrameDecoder()
        decoder.feed(partial)
        with pytest.raises(AdminProtocolError, match="incomplete"):
            decoder.finish()
    with pytest.raises(AdminProtocolError, match="bounded"):
        AdminFrameDecoder().feed(b"x" * 65_537)


def test_uint64_money_wire_bits_are_signed_without_precision_loss() -> None:
    payload = struct.pack("<BQQQHqHHqHH", 0, 2**64 - 1, 0, 2**63, 0, 0, 0, 0, 0, 0, 0)
    economy = decode_server_packet(117, payload)
    assert isinstance(economy, CompanyEconomyObservation)
    assert economy.cash_balance_gbp == -1
    assert economy.admin_year_to_date_net_income_gbp == -(2**63)


def test_rejection_lifecycle_company_change_and_pong_packets() -> None:
    assert isinstance(decode_server_packet(100, b""), ServerFull)
    assert isinstance(decode_server_packet(101, b""), ServerBanned)
    assert decode_server_packet(102, b"\x03") == ServerError(error_code=3)
    assert isinstance(decode_server_packet(105, b""), ServerNewGame)
    assert isinstance(decode_server_packet(106, b""), ServerShutdown)
    assert decode_server_packet(113, b"\x02") == CompanyNew(company_id=2)
    assert decode_server_packet(116, b"\x02\x01") == CompanyRemove(company_id=2, reason_code=1)
    update = decode_server_packet(
        115,
        b"\x02New Name\0Manager\0" + struct.pack("<BBB4B", 4, 1, 2, 255, 255, 255, 255),
    )
    assert isinstance(update, CompanyUpdate)
    assert (update.company_id, update.name, update.bankruptcy_quarters) == (2, "New Name", 2)
    assert decode_server_packet(126, struct.pack("<I", 42)) == ServerPong(token=42)
    with pytest.raises(AdminProtocolError, match="truncated"):
        decode_server_packet(102, b"")


def test_duplicate_protocol_update_type_is_rejected() -> None:
    duplicate = b"\x02" + struct.pack("<BHHBHHB", 1, 0, 63, 1, 0, 63, 0)
    with pytest.raises(AdminProtocolError, match="duplicate update type"):
        decode_server_packet(103, duplicate)


def test_production_protocol_and_types_do_not_import_prototype_runtime() -> None:
    root = Path(__file__).resolve().parents[1] / "app/simulation/openttd"
    for filename in ("admin_protocol.py", "telemetry.py"):
        syntax = ast.parse((root / filename).read_text())
        imports = (
            node.module if isinstance(node, ast.ImportFrom) else alias.name
            for node in ast.walk(syntax)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in (node.names if isinstance(node, ast.Import) else [None])
        )
        assert all(not (name or "").startswith("prototype") for name in imports)


def test_read_only_admin_client_packets_follow_13_4_wire_layouts() -> None:
    # Synthesized from tcp_admin.h and packet.cpp at tag 13.4.
    assert encode_admin_join("password", "observer", "1") == _frame(
        0, b"password\0observer\0" + b"1\0"
    )
    assert encode_admin_quit() == _frame(1)
    assert encode_admin_update_frequency(AdminUpdateType.DATE, AdminFrequency.DAILY) == _frame(
        2, struct.pack("<HH", 0, 2)
    )
    assert encode_admin_poll(AdminUpdateType.COMPANY_INFO, 2) == _frame(3, struct.pack("<BI", 2, 2))
    assert encode_admin_ping(42) == _frame(7, struct.pack("<I", 42))
    with pytest.raises(AdminProtocolError):
        encode_admin_join("bad\0password", "observer", "1")
    with pytest.raises(AdminProtocolError):
        encode_admin_poll(AdminUpdateType.DATE, -1)
