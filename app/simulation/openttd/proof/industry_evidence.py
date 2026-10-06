"""One native industry transaction plus startup, independent of Python clock order."""

import hashlib
import re
from dataclasses import dataclass

from app.simulation.openttd.industry_page import IndustryPageRequest, IndustryPageResponse
from app.simulation.openttd.industry_page_evidence import (
    IndustryPageEvidence,
    parse_industry_page_evidence,
)

from .industry_contract import INDUSTRY_INTERNAL_CHAIN

_START = re.compile(
    r"(?:\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\] )?dbg: \[script:4\] \[18\] \[I\] "
    r"BRIDGE_STARTED protocol=1 api=15"
)


@dataclass(frozen=True)
class IndustryProofEvidence:
    startup_line: int | None
    page: IndustryPageEvidence
    response_digest: str | None = None
    response_digest_source: str = "Python retained protocol response; not a native hash observation"

    @property
    def ordered_sequence(self) -> tuple[str, ...]:
        return (
            () if self.startup_line is None else ("BRIDGE_STARTED",)
        ) + self.page.ordered_sequence

    def correlate(self, request: IndustryPageRequest, response: bytes) -> IndustryProofEvidence:
        if self.ordered_sequence != INDUSTRY_INTERNAL_CHAIN:
            raise ValueError("Incomplete industry startup/read/send/liveness evidence")
        replay = parse_industry_proof_evidence(
            self.page.raw_log, request.request_id, source_log=self.page.source_log
        )
        if replay.startup_line != self.startup_line or replay.page != self.page:
            raise ValueError("Industry evidence replay mismatch")
        self.page.require_complete(request, IndustryPageResponse.parse(response))
        digest = hashlib.sha256(response).hexdigest()
        if self.response_digest is not None and self.response_digest != digest:
            raise ValueError("Industry evidence/response digest mismatch")
        return IndustryProofEvidence(self.startup_line, self.page, digest)


def parse_industry_proof_evidence(
    raw: bytes, request_id: str, *, source_log: str = "stderr.log"
) -> IndustryProofEvidence:
    page = parse_industry_page_evidence(raw, request_id, source_log=source_log)
    startup = None
    for number, line in enumerate(raw.splitlines(keepends=True), 1):
        if not line.endswith(b"\n"):
            continue
        text = line.decode("utf-8", errors="strict").rstrip("\r\n")
        if "BRIDGE_STARTED" in text:
            if not _START.fullmatch(text) or startup is not None:
                raise ValueError("Malformed/duplicate native industry startup")
            startup = number
        identity = re.search(r"(?:BRIDGE_|INDUSTRY_PAGE_)\w+ request_id=([^\s]+)", text)
        if identity and identity[1] != request_id:
            raise ValueError("Unrelated transaction in single-query industry proof")
    if page.line_numbers and (startup is None or startup >= page.line_numbers[0]):
        raise ValueError("Industry transaction before startup")
    return IndustryProofEvidence(startup, page)
