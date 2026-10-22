"""Command-specific independent GS channel, following existing marker conventions."""

import hashlib
import re
from dataclasses import dataclass

from app.simulation.openttd.tile_facts import (
    TileFactsExchange,
    TileFactsRequest,
    TileFailure,
    TileQueryError,
)

GS_SEQUENCE = (
    "BRIDGE_REQUEST_RECEIVED",
    "TILE_FACTS_READ",
    "BRIDGE_RESPONSE_SENT",
    "BRIDGE_POST_RESPONSE_ALIVE",
)
MARKER = re.compile(
    r"(?:\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\] )?dbg: \[script:4\] \[18\] \[I\] "
    r"(BRIDGE_REQUEST_RECEIVED|TILE_FACTS_READ|BRIDGE_RESPONSE_SENT|BRIDGE_POST_RESPONSE_ALIVE)"
    r" request_id=([A-Za-z0-9_-]+)(.*)"
)


@dataclass(frozen=True)
class TileFactsEvidence:
    request_id: str
    ordered_sequence: tuple[str, ...]
    suffixes: tuple[str, ...]
    line_numbers: tuple[int, ...]
    raw_log: bytes
    raw_digest: str

    def require_complete(self, exchange: TileFactsExchange):
        exchange.validate()
        q = TileFactsRequest.parse(exchange.request_payload)
        if (
            self != parse_tile_facts_evidence(self.raw_log, q.request_id)
            or self.ordered_sequence != GS_SEQUENCE
            or self.request_id != q.request_id
        ):
            raise TileQueryError(TileFailure.BRIDGE_FAILURE)
        expected = (
            " type=tile_facts_page protocol=1",
            " response_json=" + exchange.response.to_bytes().decode("ascii"),
            " type=tile_facts_page_result status=ok protocol=1",
            "",
        )
        if self.suffixes != expected:
            raise TileQueryError(TileFailure.BRIDGE_FAILURE)
        # Canonical native log bytes independently identify the semantic response;
        # receipt SHA-256 binds exact on-wire bytes (ordering/whitespace can differ).


def parse_tile_facts_evidence(raw: bytes, request_id: str) -> TileFactsEvidence:
    from app.simulation.openttd.observation_protocol import validate_request_id

    validate_request_id(request_id)
    seq = []
    suffix = []
    numbers = []
    for n, line in enumerate(raw.splitlines(keepends=True), 1):
        text = line.decode("utf-8", errors="strict").rstrip("\r\n")
        m = MARKER.fullmatch(text)
        relevant = re.search(rf"request_id={re.escape(request_id)}(?:\s|$)", text)
        if (
            relevant
            and ("BRIDGE_" in text or "TILE_FACTS_" in text)
            and (m is None or not line.endswith(b"\n"))
        ):
            raise TileQueryError(TileFailure.BRIDGE_FAILURE)
        if not m or m.group(2) != request_id:
            continue
        if len(seq) >= 4 or m.group(1) != GS_SEQUENCE[len(seq)]:
            raise TileQueryError(TileFailure.BRIDGE_FAILURE)
        seq.append(m.group(1))
        suffix.append(m.group(3))
        numbers.append(n)
    return TileFactsEvidence(
        request_id, tuple(seq), tuple(suffix), tuple(numbers), raw, hashlib.sha256(raw).hexdigest()
    )
