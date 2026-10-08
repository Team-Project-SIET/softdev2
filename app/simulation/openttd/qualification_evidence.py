"""Native clock/lifetime partial order and exact DTO correlation, not transport alone."""

import hashlib
import re
from dataclasses import dataclass

from app.simulation.openttd.observation_protocol import validate_request_id
from app.simulation.openttd.qualification_clock import NativeReadExchange

_MARKER = re.compile(
    r"(?:\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\] )?dbg: \[script:4\] \[18\] \[I\] "
    r"(BRIDGE_REQUEST_RECEIVED|ECONOMY_CLOCK_READ|INDUSTRY_LIFETIME_READ|BRIDGE_RESPONSE_SENT|BRIDGE_POST_RESPONSE_ALIVE)"
    r" request_id=([A-Za-z0-9_-]+)(.*)"
)


@dataclass(frozen=True)
class NativeReadEvidence:
    request_id: str
    command: str
    sequence: tuple[str, ...]
    suffixes: tuple[str, ...]
    line_numbers: tuple[int, ...]
    raw_log: bytes
    raw_digest: str

    def require_complete(self, exchange: NativeReadExchange):
        exchange.validate()
        request, response = exchange.request, exchange.response
        if (
            self != parse_native_read_evidence(self.raw_log, self.request_id, self.command)
            or self.request_id != request.request_id
            or self.command != request.command
        ):
            raise ValueError("native read evidence identity mismatch")
        names = response.reading.__dataclass_fields__
        expected = (
            " type=" + request.command + " protocol=1",
            "".join(f" {name}={getattr(response.reading, name)}" for name in names),
            " type=" + request.command + "_result status=ok protocol=1",
            "",
        )
        if self.sequence != native_sequence(self.command) or self.suffixes != expected:
            raise ValueError("missing/noncanonical native read or liveness evidence")


def native_sequence(command):
    if command not in ("economy_clock", "industry_lifetime"):
        raise ValueError("unsupported native read command")
    return (
        "BRIDGE_REQUEST_RECEIVED",
        command.upper() + "_READ",
        "BRIDGE_RESPONSE_SENT",
        "BRIDGE_POST_RESPONSE_ALIVE",
    )


def parse_native_read_evidence(raw: bytes, request_id: str, command: str):
    validate_request_id(request_id)
    expected = native_sequence(command)
    markers, suffixes, numbers = [], [], []
    for number, line in enumerate(raw.splitlines(keepends=True), 1):
        if not line.endswith(b"\n"):
            continue
        text = line.decode("utf-8", errors="strict").rstrip("\r\n")
        match = _MARKER.fullmatch(text)
        if match is None:
            if re.search(rf"request_id={re.escape(request_id)}(?:\s|$)", text) and (
                "BRIDGE_" in text or "_READ" in text
            ):
                raise ValueError("malformed native read evidence")
            continue
        marker, identity, suffix = match.groups()
        if identity != request_id:
            continue
        if len(markers) >= 4 or marker != expected[len(markers)]:
            raise ValueError("duplicate/out-of-order native read evidence")
        markers.append(marker)
        suffixes.append(suffix)
        numbers.append(number)
    return NativeReadEvidence(
        request_id,
        command,
        tuple(markers),
        tuple(suffixes),
        tuple(numbers),
        raw,
        hashlib.sha256(raw).hexdigest(),
    )


@dataclass(frozen=True)
class NativeReadTransaction:
    exchange: NativeReadExchange
    gamescript: NativeReadEvidence

    def validate(self):
        self.gamescript.require_complete(self.exchange)
