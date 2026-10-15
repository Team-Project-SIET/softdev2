"""Strict canonical per-industry native evidence, with local partial order."""

import hashlib
import re
from dataclasses import dataclass

from app.simulation.openttd.industry_production import (
    IndustryProductionExchange,
    IndustryProductionRequest,
    IndustryProductionResponse,
)
from app.simulation.openttd.observation_protocol import validate_request_id

PRODUCTION_GS_SEQUENCE = (
    "BRIDGE_REQUEST_RECEIVED",
    "INDUSTRY_PRODUCTION_READ",
    "BRIDGE_RESPONSE_SENT",
    "BRIDGE_POST_RESPONSE_ALIVE",
)
_MARKER = re.compile(
    r"(?:\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\] )?dbg: \[script:4\] \[18\] \[I\] "
    r"(BRIDGE_REQUEST_RECEIVED|INDUSTRY_PRODUCTION_READ|BRIDGE_RESPONSE_SENT|BRIDGE_POST_RESPONSE_ALIVE)"
    r" request_id=([A-Za-z0-9_-]+)(.*)"
)


@dataclass(frozen=True)
class IndustryProductionEvidence:
    request_id: str
    ordered_sequence: tuple[str, ...]
    suffixes: tuple[str, ...]
    line_numbers: tuple[int, ...]
    raw_log: bytes
    raw_digest: str

    def require_complete(
        self, request: IndustryProductionRequest, response: IndustryProductionResponse
    ):
        if (
            self != parse_industry_production_evidence(self.raw_log, self.request_id)
            or self.ordered_sequence != PRODUCTION_GS_SEQUENCE
            or self.request_id != request.request_id
            or response.request_id != request.request_id
            or response.record.pair != (request.industry_id, request.cargo_id)
        ):
            raise ValueError("incomplete/correlation industry production evidence")
        record = response.record
        expected = (
            " type=industry_production protocol=1",
            "".join(f" {name}={getattr(record, name)}" for name in record.__dataclass_fields__),
            " type=industry_production_result status=ok protocol=1",
            "",
        )
        if self.suffixes != expected:
            raise ValueError("noncanonical industry production metadata")


def parse_industry_production_evidence(raw: bytes, request_id: str) -> IndustryProductionEvidence:
    validate_request_id(request_id)
    markers, suffixes, numbers = [], [], []
    for number, line in enumerate(raw.splitlines(keepends=True), 1):
        if not line.endswith(b"\n"):
            continue
        text = line.decode("utf-8", errors="strict").rstrip("\r\n")
        match = _MARKER.fullmatch(text)
        if match is None:
            if re.search(rf"request_id={re.escape(request_id)}(?:\s|$)", text) and (
                "BRIDGE_" in text or "INDUSTRY_PRODUCTION_" in text
            ):
                raise ValueError("malformed cargo evidence")
            continue
        marker, identity, suffix = match.groups()
        if identity != request_id:
            continue
        if len(markers) >= 4 or marker != PRODUCTION_GS_SEQUENCE[len(markers)]:
            raise ValueError("duplicate/out-of-order cargo evidence")
        markers.append(marker)
        suffixes.append(suffix)
        numbers.append(number)
    return IndustryProductionEvidence(
        request_id,
        tuple(markers),
        tuple(suffixes),
        tuple(numbers),
        raw,
        hashlib.sha256(raw).hexdigest(),
    )


@dataclass(frozen=True)
class ProductionTransaction:
    exchange: IndustryProductionExchange
    gamescript: IndustryProductionEvidence

    def validate(self):
        self.exchange.validate()
        self.gamescript.require_complete(
            IndustryProductionRequest.parse(self.exchange.request_payload), self.exchange.response
        )
