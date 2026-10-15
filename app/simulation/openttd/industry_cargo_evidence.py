"""Strict canonical per-industry native evidence, with local partial order."""

import hashlib
import re
from dataclasses import dataclass

from app.simulation.openttd.industry_cargo import IndustryCargoRequest, IndustryCargoResponse
from app.simulation.openttd.observation_protocol import validate_request_id

CARGO_GS_SEQUENCE = (
    "BRIDGE_REQUEST_RECEIVED",
    "INDUSTRY_CARGO_READ",
    "BRIDGE_RESPONSE_SENT",
    "BRIDGE_POST_RESPONSE_ALIVE",
)
_MARKER = re.compile(
    r"(?:\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\] )?dbg: \[script:4\] \[18\] \[I\] "
    r"(BRIDGE_REQUEST_RECEIVED|INDUSTRY_CARGO_READ|BRIDGE_RESPONSE_SENT|BRIDGE_POST_RESPONSE_ALIVE)"
    r" request_id=([A-Za-z0-9_-]+)(.*)"
)


@dataclass(frozen=True)
class IndustryCargoEvidence:
    request_id: str
    ordered_sequence: tuple[str, ...]
    suffixes: tuple[str, ...]
    line_numbers: tuple[int, ...]
    raw_log: bytes
    raw_digest: str

    def require_complete(self, request: IndustryCargoRequest, response: IndustryCargoResponse):
        if (
            self != parse_industry_cargo_evidence(self.raw_log, self.request_id)
            or self.ordered_sequence != CARGO_GS_SEQUENCE
            or self.request_id != request.request_id
            or response.request_id != request.request_id
            or response.capability.industry_id != request.industry_id
        ):
            raise ValueError("incomplete/correlation industry cargo evidence")
        cap = response.capability

        def bounds(values):
            return (str(values[0]), str(values[-1])) if values else ("null", "null")

        pf, pl = bounds(cap.produces)
        af, al = bounds(cap.accepts)
        expected = (
            " type=industry_cargo protocol=1",
            f" industry_id={cap.industry_id} produced_count={len(cap.produces)}"
            f" accepted_count={len(cap.accepts)} first_produced={pf} last_produced={pl}"
            f" first_accepted={af} last_accepted={al}",
            " type=industry_cargo_result status=ok protocol=1",
            "",
        )
        if self.suffixes != expected:
            raise ValueError("noncanonical industry cargo metadata")


def parse_industry_cargo_evidence(raw: bytes, request_id: str) -> IndustryCargoEvidence:
    validate_request_id(request_id)
    markers, suffixes, numbers = [], [], []
    for number, line in enumerate(raw.splitlines(keepends=True), 1):
        if not line.endswith(b"\n"):
            continue
        text = line.decode("utf-8", errors="strict").rstrip("\r\n")
        match = _MARKER.fullmatch(text)
        if match is None:
            if re.search(rf"request_id={re.escape(request_id)}(?:\s|$)", text) and (
                "BRIDGE_" in text or "INDUSTRY_CARGO_" in text
            ):
                raise ValueError("malformed cargo evidence")
            continue
        marker, identity, suffix = match.groups()
        if identity != request_id:
            continue
        if len(markers) >= 4 or marker != CARGO_GS_SEQUENCE[len(markers)]:
            raise ValueError("duplicate/out-of-order cargo evidence")
        markers.append(marker)
        suffixes.append(suffix)
        numbers.append(number)
    return IndustryCargoEvidence(
        request_id,
        tuple(markers),
        tuple(suffixes),
        tuple(numbers),
        raw,
        hashlib.sha256(raw).hexdigest(),
    )
