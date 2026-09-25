"""Narrow OpenTTD 13.4 Admin Network framing and server-packet decoding.

Layouts: docs/admin_network.md, network/core/tcp_admin.h,
network/network_admin.cpp, network/core/packet.cpp at the OpenTTD 13.4 tag.
"""

import struct
from dataclasses import dataclass
from enum import IntEnum, IntFlag

from app.simulation.openttd.telemetry import (
    CompanyEconomyObservation,
    CompanyInfoObservation,
    CompanyStatsObservation,
    CompletedQuarter,
    GameDateObservation,
    PrimaryVehicleCounts,
    StationFacilityCounts,
    supported_game_day_to_date,
)


class AdminProtocolError(ValueError):
    """A known packet or frame has an invalid or truncated layout."""


class AdminUpdateType(IntEnum):
    DATE = 0
    COMPANY_INFO = 2
    COMPANY_ECONOMY = 3
    COMPANY_STATS = 4


class AdminFrequency(IntFlag):
    POLL = 0x01
    DAILY = 0x02
    WEEKLY = 0x04
    MONTHLY = 0x08
    QUARTERLY = 0x10
    ANNUALLY = 0x20
    AUTOMATIC = 0x40


@dataclass(frozen=True)
class ServerProtocol:
    version: int
    advertised_frequencies: tuple[tuple[int, int], ...]

    @property
    def frequencies(self) -> dict[int, int]:
        return dict(self.advertised_frequencies)

    def supports(self, update_type: AdminUpdateType, frequency: AdminFrequency) -> bool:
        mask = self.frequencies.get(update_type, 0)
        return mask & int(frequency) == int(frequency)


@dataclass(frozen=True)
class ServerWelcome:
    name: str
    revision: str
    dedicated: bool
    map_name: str
    seed: int
    landscape: int
    start_day: int
    width: int
    height: int


@dataclass(frozen=True)
class ServerFull:
    pass


@dataclass(frozen=True)
class ServerBanned:
    pass


@dataclass(frozen=True)
class ServerError:
    error_code: int


@dataclass(frozen=True)
class ServerNewGame:
    pass


@dataclass(frozen=True)
class ServerShutdown:
    pass


@dataclass(frozen=True)
class CompanyNew:
    company_id: int


@dataclass(frozen=True)
class CompanyUpdate:
    company_id: int
    name: str
    manager: str
    colour: int
    password_protected: bool
    bankruptcy_quarters: int
    share_owners: tuple[int, ...]


@dataclass(frozen=True)
class CompanyRemove:
    company_id: int
    reason_code: int


@dataclass(frozen=True)
class ServerPong:
    token: int


@dataclass(frozen=True)
class UnknownPacket:
    """Bounded metadata only; unsupported packet bodies are discarded."""

    packet_id: int
    payload_length: int


type ServerPacket = (
    ServerProtocol
    | ServerWelcome
    | ServerFull
    | ServerBanned
    | ServerError
    | ServerNewGame
    | ServerShutdown
    | GameDateObservation
    | CompanyNew
    | CompanyInfoObservation
    | CompanyUpdate
    | CompanyRemove
    | CompanyEconomyObservation
    | CompanyStatsObservation
    | ServerPong
    | UnknownPacket
)


class _Reader:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.position = 0

    def read(self, format: str) -> tuple[int, ...]:
        try:
            values = struct.unpack_from("<" + format, self.payload, self.position)
        except struct.error as exc:
            raise AdminProtocolError("truncated Admin packet") from exc
        self.position += struct.calcsize("<" + format)
        return values

    def string(self) -> str:
        end = self.payload.find(b"\0", self.position)
        if end < 0:
            raise AdminProtocolError("unterminated Admin string")
        if end - self.position > 1024:
            raise AdminProtocolError("Admin string exceeds supported length")
        raw = self.payload[self.position : end]
        self.position = end + 1
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AdminProtocolError("invalid UTF-8 in Admin string") from exc

    def boolean(self) -> bool:
        # packet.cpp::Recv_bool accepts any nonzero uint8 as true.
        return self.read("B")[0] != 0


def _company_id(value: int) -> int:
    # company_type.h: MAX_COMPANIES = 0x0F, valid IDs are 0..14.
    if not 0 <= value <= 14:
        raise AdminProtocolError("company ID outside OpenTTD 13.4 range")
    return value


def _completed_quarter(reader: _Reader, offset: int) -> CompletedQuarter:
    return CompletedQuarter(
        history_offset=offset,
        company_value_gbp=reader.read("q")[0],
        performance_score=reader.read("H")[0],
        delivered_cargo_capped=reader.read("H")[0],
    )


def decode_server_packet(packet_id: int, payload: bytes) -> ServerPacket:
    """Decode only packets needed by the planned read-only observer.

    Known packets may have appended fields; unknown IDs return bounded metadata.
    """
    if not 0 <= packet_id <= 255:
        raise AdminProtocolError("packet ID outside uint8 range")
    reader = _Reader(payload)
    if packet_id == 100:
        return ServerFull()
    if packet_id == 101:
        return ServerBanned()
    if packet_id == 102:
        return ServerError(reader.read("B")[0])
    if packet_id == 103:
        version = reader.read("B")[0]
        frequencies: list[tuple[int, int]] = []
        seen: set[int] = set()
        while reader.boolean():
            update_type, mask = reader.read("HH")
            if update_type in seen:
                raise AdminProtocolError("duplicate update type in ServerProtocol")
            seen.add(update_type)
            frequencies.append((update_type, mask))
        return ServerProtocol(version, tuple(frequencies))
    if packet_id == 104:
        name = reader.string()
        revision = reader.string()
        dedicated = reader.boolean()
        map_name = reader.string()
        seed, landscape, start_day, width, height = reader.read("IBIHH")
        supported_game_day_to_date(start_day)
        return ServerWelcome(
            name, revision, dedicated, map_name, seed, landscape, start_day, width, height
        )
    if packet_id == 105:
        return ServerNewGame()
    if packet_id == 106:
        return ServerShutdown()
    if packet_id == 107:
        return GameDateObservation(game_day=reader.read("I")[0])
    if packet_id == 113:
        return CompanyNew(_company_id(reader.read("B")[0]))
    if packet_id == 114:
        company_id = _company_id(reader.read("B")[0])
        name = reader.string()
        manager = reader.string()
        colour = reader.read("B")[0]
        password_protected = reader.boolean()
        inaugurated_year = reader.read("I")[0]
        is_ai = reader.boolean()
        bankruptcy_quarters = reader.read("B")[0]
        owners = reader.read("4B")
        return CompanyInfoObservation(
            company_id=company_id,
            name=name,
            manager=manager,
            colour=colour,
            password_protected=password_protected,
            inaugurated_year=inaugurated_year,
            is_ai=is_ai,
            bankruptcy_quarters=bankruptcy_quarters,
            share_owners=(owners[0], owners[1], owners[2], owners[3]),
        )
    if packet_id == 115:
        company_id = _company_id(reader.read("B")[0])
        name, manager = reader.string(), reader.string()
        colour = reader.read("B")[0]
        password_protected = reader.boolean()
        bankruptcy_quarters = reader.read("B")[0]
        share_owners = reader.read("4B")
        return CompanyUpdate(
            company_id,
            name,
            manager,
            colour,
            password_protected,
            bankruptcy_quarters,
            share_owners,
        )
    if packet_id == 116:
        return CompanyRemove(_company_id(reader.read("B")[0]), reader.read("B")[0])
    if packet_id == 117:
        company_id = _company_id(reader.read("B")[0])
        money, loan, income = reader.read("qqq")
        current_cargo = reader.read("H")[0]
        quarters = (_completed_quarter(reader, 1), _completed_quarter(reader, 2))
        return CompanyEconomyObservation(
            company_id=company_id,
            cash_balance_gbp=money,
            loan_balance_gbp=loan,
            admin_year_to_date_net_income_gbp=income,
            current_quarter_delivered_cargo_capped=current_cargo,
            completed_quarters=quarters,
        )
    if packet_id == 118:
        company_id = _company_id(reader.read("B")[0])
        vehicles, stations = reader.read("5H"), reader.read("5H")
        return CompanyStatsObservation(
            company_id=company_id,
            primary_vehicles=PrimaryVehicleCounts(
                train=vehicles[0],
                lorry=vehicles[1],
                bus=vehicles[2],
                plane=vehicles[3],
                ship=vehicles[4],
            ),
            station_facilities=StationFacilityCounts(
                train_station=stations[0],
                lorry_station=stations[1],
                bus_stop=stations[2],
                airport_or_heliport=stations[3],
                harbour=stations[4],
            ),
        )
    if packet_id == 126:
        return ServerPong(reader.read("I")[0])
    return UnknownPacket(packet_id=packet_id, payload_length=len(payload))


class AdminFrameDecoder:
    """Incremental, bounded decoder for 13.4's uint16 length + uint8 ID frames."""

    MAX_FRAME_LENGTH = 32767  # TCP_MTU in 13.4 src/network/core/config.h.
    MAX_FEED_BYTES = 65536

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._closed = False

    def feed(self, chunk: bytes) -> list[ServerPacket]:
        if self._closed:
            raise AdminProtocolError("frame decoder is closed")
        if len(chunk) > self.MAX_FEED_BYTES:
            raise AdminProtocolError("Admin input chunk exceeds bounded length")
        self._buffer.extend(chunk)
        packets: list[ServerPacket] = []
        while len(self._buffer) >= 2:
            length = self._buffer[0] | (self._buffer[1] << 8)
            if not 3 <= length <= self.MAX_FRAME_LENGTH:
                raise AdminProtocolError("invalid Admin frame length")
            if len(self._buffer) < length:
                break
            packet_id = self._buffer[2]
            payload = bytes(self._buffer[3:length])
            del self._buffer[:length]
            packets.append(decode_server_packet(packet_id, payload))
        return packets

    def finish(self) -> None:
        self._closed = True
        if self._buffer:
            raise AdminProtocolError("incomplete Admin frame at EOF")
