"""One native cargo-page transaction plus startup, independent of Python clock order."""

import hashlib
import re
from dataclasses import dataclass

from app.simulation.openttd.cargo_page import CargoPageRequest, CargoPageResponse
from app.simulation.openttd.cargo_page_evidence import (
    CargoPageEvidence,
    parse_cargo_page_evidence,
)

from .cargo_page_contract import PAGE_INTERNAL_CHAIN

_START = re.compile(
    r"(?:\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\] )?dbg: \[script:4\] \[18\] \[I\] "
    r"BRIDGE_STARTED protocol=1 api=15"
)


@dataclass(frozen=True)
class CargoPageProofEvidence:
    startup_line: int | None
    cargo: CargoPageEvidence
    response_digest: str | None = None
    source_log: str = "stderr.log"
    response_digest_source: str = "Python retained protocol response; not a native hash observation"

    @property
    def ordered_sequence(self) -> tuple[str, ...]:
        return (
            () if self.startup_line is None else ("BRIDGE_STARTED",)
        ) + self.cargo.ordered_sequence

    def correlate(self, request: CargoPageRequest, response: bytes) -> CargoPageProofEvidence:
        if self.ordered_sequence != PAGE_INTERNAL_CHAIN:
            raise ValueError("Incomplete cargo-page startup/read/send/liveness evidence")
        replay = parse_page_proof_evidence(
            self.cargo.raw_log, request.request_id, source_log=self.source_log
        )
        if replay.startup_line != self.startup_line or replay.cargo != self.cargo:
            raise ValueError("Cargo page evidence replay mismatch")
        self.cargo.require_complete(request, CargoPageResponse.parse(response))
        digest = hashlib.sha256(response).hexdigest()
        if self.response_digest is not None and self.response_digest != digest:
            raise ValueError("Cargo page evidence/response digest mismatch")
        return CargoPageProofEvidence(self.startup_line, self.cargo, digest, self.source_log)


def parse_page_proof_evidence(
    raw: bytes, request_id: str, *, source_log: str = "stderr.log"
) -> CargoPageProofEvidence:
    page = parse_cargo_page_evidence(raw, request_id, source_log=source_log)
    startup = None
    for number, line in enumerate(raw.splitlines(keepends=True), 1):
        if not line.endswith(b"\n"):
            continue
        text = line.decode("utf-8", errors="strict").rstrip("\r\n")
        if "BRIDGE_STARTED" in text:
            if not _START.fullmatch(text) or startup is not None:
                raise ValueError("Malformed/duplicate native cargo-page startup")
            startup = number
        identity = re.search(r"(?:BRIDGE_|CARGO_PAGE_)\w+ request_id=([^\s]+)", text)
        if identity and identity[1] != request_id:
            raise ValueError("Unrelated transaction in single-query cargo-page proof")
    if page.line_numbers and (startup is None or startup >= page.line_numbers[0]):
        raise ValueError("Cargo page transaction before startup")
    return CargoPageProofEvidence(startup, page, source_log=source_log)
