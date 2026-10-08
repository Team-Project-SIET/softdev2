"""Bounded native economy identity and industry lifetime reads; no qualification state."""

import hashlib
import json
from dataclasses import asdict, dataclass

from app.simulation.openttd.industry_page import MAX_INDUSTRY_ID, _integer
from app.simulation.openttd.observation_protocol import (
    BridgeProtocolError,
    _object,
    _serialize,
    validate_request_id,
)


def year_start(year):
    leaps = 0 if year == 0 else (year - 1) // 4 - (year - 1) // 100 + (year - 1) // 400 + 1
    return 365 * year + leaps


def calendar_bounds(year, month):
    _integer(year, 5000000, "economy year")
    if type(month) is not int or not 1 <= month <= 12:
        raise BridgeProtocolError("invalid economy month")
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    lengths = (31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    start = year_start(year) + sum(lengths[: month - 1])
    return start, start + lengths[month - 1]


def native_calendar_month(year, month):
    from app.simulation.openttd.production_observation import EconomyMonth

    start, end = calendar_bounds(year, month)
    return EconomyMonth(year, month, start, end)


@dataclass(frozen=True)
class EconomyClockRequest:
    request_id: str

    def __post_init__(self):
        validate_request_id(self.request_id)

    @property
    def command(self):
        return "economy_clock"

    def to_bytes(self):
        return _serialize(dict(protocol=1, type=self.command, **asdict(self)))

    @classmethod
    def parse(cls, payload):
        v = _object(payload, "economy_clock", {"protocol", "type", "request_id"})
        return cls(validate_request_id(v["request_id"]))


@dataclass(frozen=True)
class IndustryLifetimeRequest:
    request_id: str
    industry_id: int

    def __post_init__(self):
        validate_request_id(self.request_id)
        _integer(self.industry_id, MAX_INDUSTRY_ID, "industry ID")

    @property
    def command(self):
        return "industry_lifetime"

    def to_bytes(self):
        return _serialize(dict(protocol=1, type=self.command, **asdict(self)))

    @classmethod
    def parse(cls, payload):
        v = _object(payload, "industry_lifetime", {"protocol", "type", "request_id", "industry_id"})
        return cls(
            validate_request_id(v["request_id"]),
            _integer(v["industry_id"], MAX_INDUSTRY_ID, "industry ID"),
        )


@dataclass(frozen=True)
class EconomyClockReading:
    economy_date: int
    economy_year: int
    economy_month: int
    economy_day: int
    month_start: int
    month_end: int

    def __post_init__(self):
        for v in asdict(self).values():
            _integer(v, 2147483647, "clock scalar")
        if self.economy_year == 5000000 and self.economy_month == 12:
            raise BridgeProtocolError("native next-month boundary unavailable at maximum year")
        start, end = calendar_bounds(self.economy_year, self.economy_month)
        if (
            self.month_start != start
            or self.month_end != end
            or not 1 <= self.economy_day <= end - start
            or self.economy_date != start + self.economy_day - 1
        ):
            raise BridgeProtocolError("native calendar-time clock identity incoherent")

    @property
    def month(self):
        return native_calendar_month(self.economy_year, self.economy_month)


@dataclass(frozen=True)
class IndustryLifetimeReading:
    industry_id: int
    construction_date: int  # Native CALENDAR date, comparable only in pinned calendar mode.
    economy_before: int
    economy_after: int

    def __post_init__(self):
        _integer(self.industry_id, MAX_INDUSTRY_ID, "industry ID")
        for v in (self.construction_date, self.economy_before, self.economy_after):
            _integer(v, 2147483647, "lifetime date")
        if self.economy_before > self.economy_after:
            raise BridgeProtocolError("invalid native lifetime brackets")


@dataclass(frozen=True)
class NativeReadResponse:
    request_id: str
    reading: EconomyClockReading | IndustryLifetimeReading

    def __post_init__(self):
        validate_request_id(self.request_id)
        if not isinstance(self.reading, (EconomyClockReading, IndustryLifetimeReading)):
            raise BridgeProtocolError("typed native read required")

    @property
    def command(self):
        return (
            "economy_clock"
            if isinstance(self.reading, EconomyClockReading)
            else "industry_lifetime"
        )

    def to_bytes(self):
        return _serialize(
            dict(
                protocol=1,
                type=self.command + "_result",
                request_id=self.request_id,
                status="ok",
                **asdict(self.reading),
            )
        )

    @classmethod
    def parse_for(cls, request, payload):
        record = (
            EconomyClockReading
            if isinstance(request, EconomyClockRequest)
            else IndustryLifetimeReading
        )
        v = _object(
            payload,
            request.command + "_result",
            {"protocol", "type", "request_id", "status", *record.__dataclass_fields__},
        )
        if v["status"] != "ok" or v["request_id"] != request.request_id:
            raise BridgeProtocolError("native clock/lifetime response correlation failed")
        scalars = {k: _integer(v[k], 2147483647, k) for k in record.__dataclass_fields__}
        result = cls(validate_request_id(v["request_id"]), record(**scalars))
        if (
            isinstance(request, IndustryLifetimeRequest)
            and isinstance(result.reading, IndustryLifetimeReading)
            and result.reading.industry_id != request.industry_id
        ):
            raise BridgeProtocolError("wrong lifetime industry")
        return result


def parse_native_request(payload):
    try:
        kind = json.loads(payload)["type"]
    except (ValueError, KeyError, TypeError) as error:
        raise BridgeProtocolError("malformed native read request") from error
    if kind == "economy_clock":
        return EconomyClockRequest.parse(payload)
    if kind == "industry_lifetime":
        return IndustryLifetimeRequest.parse(payload)
    raise BridgeProtocolError("wrong native read request type")


@dataclass(frozen=True)
class NativeReadReceipt:
    request_payload_sha256: str
    response_payload_sha256: str

    @classmethod
    def correlate(cls, request, response):
        q = parse_native_request(request)
        NativeReadResponse.parse_for(q, response)
        return cls(hashlib.sha256(request).hexdigest(), hashlib.sha256(response).hexdigest())


@dataclass(frozen=True)
class NativeReadExchange:
    request_payload: bytes
    response_payload: bytes
    receipt: NativeReadReceipt
    network_sequence: tuple[str, ...]
    protocol_operations: int

    @property
    def request(self):
        return parse_native_request(self.request_payload)

    @property
    def response(self):
        return NativeReadResponse.parse_for(self.request, self.response_payload)

    def validate(self):
        if self.receipt != NativeReadReceipt.correlate(self.request_payload, self.response_payload):
            raise BridgeProtocolError("native read receipt mismatch")
        command = self.request.command.upper()
        if self.network_sequence != (
            command + "_REQUEST_SENT",
            command + "_RESPONSE_RECEIVED",
            "TRANSPORT_RECEIPT_CREATED",
            command + "_VALIDATED",
        ):
            raise BridgeProtocolError("native read semantic evidence missing")
        if type(self.protocol_operations) is not int or not 4 <= self.protocol_operations <= 8:
            raise BridgeProtocolError("native read operation bound exceeded")


MAX_CLOCK_RESPONSE_BYTES = len(
    NativeReadResponse(
        "x" * 64,
        EconomyClockReading(
            calendar_bounds(5000000, 11)[1] - 1,
            5000000,
            11,
            30,
            calendar_bounds(5000000, 11)[0],
            calendar_bounds(5000000, 11)[1],
        ),
    ).to_bytes()
)
MAX_LIFETIME_RESPONSE_BYTES = len(
    NativeReadResponse(
        "x" * 64, IndustryLifetimeReading(MAX_INDUSTRY_ID, 2147483647, 2147483647, 2147483647)
    ).to_bytes()
)

MAX_CLOCK_REQUEST_BYTES = len(EconomyClockRequest("x" * 64).to_bytes())
MAX_LIFETIME_REQUEST_BYTES = len(IndustryLifetimeRequest("x" * 64, MAX_INDUSTRY_ID).to_bytes())
