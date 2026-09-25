"""THROWAWAY: minimal OpenTTD 13.4 Admin protocol (version 2), not a general client.

Layouts checked against tag 13.4 network_admin.cpp, tcp_admin.h and packet.cpp.
Unknown packets and appended fields are deliberately ignored.
"""

import asyncio
import struct
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ServerProtocol:
    version: int
    frequencies: dict[int, int]


@dataclass(frozen=True)
class ServerWelcome:
    name: str
    revision: str
    dedicated: bool
    map_name: str
    seed: int
    landscape: int
    start_date: int
    width: int
    height: int


@dataclass(frozen=True)
class Date:
    day: int

    @property
    def iso(self) -> str:
        # OpenTTD starts at 0000-01-01; year zero has 366 days.
        return date.fromordinal(self.day - 365).isoformat()


@dataclass(frozen=True)
class CompanyInfo:
    company_id: int
    name: str
    manager: str
    colour: int
    passworded: bool
    inaugurated_year: int
    is_ai: bool
    bankruptcy_quarters: int
    share_owners: tuple[int, ...]


@dataclass(frozen=True)
class Quarter:
    value: int
    performance: int
    delivered: int


@dataclass(frozen=True)
class CompanyEconomy:
    company_id: int
    money: int
    loan: int
    income: int  # negative sum of this year's expense categories; NOT gross revenue
    delivered: int  # this quarter, saturated at 65535
    quarters: tuple[Quarter, ...]  # last quarter, then previous quarter


@dataclass(frozen=True)
class CompanyStats:
    company_id: int
    vehicles: tuple[int, ...]  # train, lorry, bus, plane, ship; primary vehicles only
    stations: tuple[int, ...]  # corresponding facility counts, not distinct stations


class Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def unpack(self, fmt: str) -> tuple:
        values = struct.unpack_from("<" + fmt, self.data, self.pos)
        self.pos += struct.calcsize("<" + fmt)
        return values

    def string(self) -> str:
        end = self.data.index(b"\0", self.pos)
        value = self.data[self.pos : end].decode("utf-8")
        self.pos = end + 1
        return value


def parse(kind: int, payload: bytes):
    r = Reader(payload)
    if kind == 103:
        (version,) = r.unpack("B")
        frequencies = {}
        while r.unpack("?")[0]:
            update, frequency = r.unpack("HH")
            frequencies[update] = frequency
        return ServerProtocol(version, frequencies)
    if kind == 104:
        name, revision = r.string(), r.string()
        (dedicated,) = r.unpack("?")
        map_name = r.string()
        return ServerWelcome(name, revision, dedicated, map_name, *r.unpack("IBIHH"))
    if kind == 107:
        return Date(*r.unpack("I"))
    if kind == 114:
        (company_id,) = r.unpack("B")
        name, manager = r.string(), r.string()
        fields = r.unpack("B?I?B")
        return CompanyInfo(company_id, name, manager, *fields, r.unpack("4B"))
    if kind == 117:
        fields = r.unpack("BqqqH")  # Money is signed int64, sent as uint64 wire bits.
        quarters = tuple(Quarter(*r.unpack("qHH")) for _ in range(2))
        return CompanyEconomy(*fields, quarters)
    if kind == 118:
        (company_id,) = r.unpack("B")
        return CompanyStats(company_id, r.unpack("5H"), r.unpack("5H"))
    return None


def frame(kind: int, payload: bytes = b"") -> bytes:
    return struct.pack("<HB", len(payload) + 3, kind) + payload


async def receive(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    (length,) = struct.unpack("<H", await reader.readexactly(2))
    if not 3 <= length <= 32767:  # 13.4 TCP_MTU (known admin packets use COMPAT_MTU)
        raise ValueError(f"Invalid packet length: {length}")
    packet = await reader.readexactly(length - 2)
    return packet[0], packet[1:]


async def send(writer: asyncio.StreamWriter, kind: int, payload: bytes = b"") -> None:
    writer.write(frame(kind, payload))
    await writer.drain()


def check_error(kind: int, payload: bytes) -> None:
    if kind in (100, 101, 102):
        code = payload[0] if payload else None
        raise RuntimeError(f"Admin rejected connection: packet={kind}, error={code}")
