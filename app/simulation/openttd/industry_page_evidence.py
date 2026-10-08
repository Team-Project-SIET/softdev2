"""Per-page native evidence: local order only, no independent inventory claim."""

import hashlib
import re
from dataclasses import dataclass

from app.simulation.openttd.industry_page import IndustryPageRequest, IndustryPageResponse
from app.simulation.openttd.observation_protocol import validate_request_id

INDUSTRY_SEQUENCE = (
    "BRIDGE_REQUEST_RECEIVED",
    "INDUSTRY_PAGE_READ",
    "BRIDGE_RESPONSE_SENT",
    "BRIDGE_POST_RESPONSE_ALIVE",
)
_NATIVE = re.compile(
    r"(?:\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\] )?dbg: \[script:4\] \[18\] \[I\] "
    r"(BRIDGE_REQUEST_RECEIVED|INDUSTRY_PAGE_READ|BRIDGE_RESPONSE_SENT|BRIDGE_POST_RESPONSE_ALIVE)"
    r" request_id=([A-Za-z0-9_-]+)(.*)"
)


@dataclass(frozen=True)
class IndustryPageEvidence:
    request_id: str
    ordered_sequence: tuple[str, ...]
    suffixes: tuple[str, ...]
    line_numbers: tuple[int, ...]
    raw_log: bytes
    source_log: str
    raw_evidence_digest: str

    def require_complete(
        self, request: IndustryPageRequest, response: IndustryPageResponse
    ) -> None:
        if self.ordered_sequence != INDUSTRY_SEQUENCE or self.request_id != request.request_id:
            raise ValueError("incomplete explicit industry page lifecycle evidence")
        if (
            parse_industry_page_evidence(self.raw_log, self.request_id, source_log=self.source_log)
            != self
        ):
            raise ValueError("industry page evidence replay mismatch")
        if response.request_id != self.request_id:
            raise ValueError("industry page response identity mismatch")
        after = "null" if request.after_id is None else str(request.after_id)
        next_cursor = "null" if response.next_after_id is None else str(response.next_after_id)
        first_id = str(response.industries[0].id) if response.industries else "null"
        last_id = str(response.industries[-1].id) if response.industries else "null"
        expected = (
            " type=industry_page protocol=1",
            f" after_id={after} limit={request.limit} returned_count={len(response.industries)}"
            f" first_id={first_id} last_id={last_id}"
            f" next_after_id={next_cursor} has_more={str(response.has_more).lower()}",
            " type=industry_page_result status=ok protocol=1",
            "",
        )
        if self.suffixes != expected:
            raise ValueError("industry page read/send metadata mismatch")


def parse_industry_page_evidence(
    raw: bytes, request_id: str, *, source_log: str = "stderr.log"
) -> IndustryPageEvidence:
    """Select one transaction from a shared multi-page log, retaining raw digest.

    Shared startup and other request IDs do not impose cross-transaction ordering.
    Unterminated lines are never accepted as completed evidence.
    """
    validate_request_id(request_id)
    markers: list[str] = []
    suffixes: list[str] = []
    numbers: list[int] = []
    for number, line in enumerate(raw.splitlines(keepends=True), 1):
        if not line.endswith(b"\n"):
            continue
        text = line.decode("utf-8", errors="strict").rstrip("\r\n")
        match = _NATIVE.fullmatch(text)
        if match is None:
            if re.search(rf"request_id={re.escape(request_id)}(?:\s|$)", text) and (
                "BRIDGE_" in text or "INDUSTRY_PAGE_" in text
            ):
                raise ValueError("malformed/non-native industry page evidence")
            continue
        marker, identity, suffix = match.groups()
        if identity != request_id:
            continue
        if len(markers) >= len(INDUSTRY_SEQUENCE) or marker != INDUSTRY_SEQUENCE[len(markers)]:
            raise ValueError("duplicate/out-of-order industry page evidence")
        markers.append(marker)
        suffixes.append(suffix)
        numbers.append(number)
    return IndustryPageEvidence(
        request_id,
        tuple(markers),
        tuple(suffixes),
        tuple(numbers),
        raw,
        source_log,
        hashlib.sha256(raw).hexdigest(),
    )
