"""Native GameScript records for world_info; no cross-process timestamp ordering."""

import hashlib
import re
from dataclasses import dataclass

from app.simulation.openttd.observation_protocol import validate_request_id
from app.simulation.openttd.world_info import WorldInfoResponse, validate_dimension

WORLD_SEQUENCE = (
    "BRIDGE_STARTED",
    "BRIDGE_REQUEST_RECEIVED",
    "WORLD_INFO_READ",
    "BRIDGE_RESPONSE_SENT",
    "BRIDGE_POST_RESPONSE_ALIVE",
)
_NATIVE = re.compile(
    r"(?:\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\] )?dbg: \[script:4\] \[18\] \[I\] "
    r"(BRIDGE_STARTED|BRIDGE_REQUEST_RECEIVED|WORLD_INFO_READ|BRIDGE_RESPONSE_SENT|BRIDGE_POST_RESPONSE_ALIVE)(.*)"
)
_READ = re.compile(r" request_id=([A-Za-z0-9_-]+) map_width=(\d+) map_height=(\d+)")


@dataclass(frozen=True)
class WorldInfoLogRecord:
    marker: str
    line_number: int
    raw_line: str


@dataclass(frozen=True)
class WorldInfoEvidence:
    request_id: str
    ordered_sequence: tuple[str, ...]
    records: tuple[WorldInfoLogRecord, ...]
    dimensions_read: tuple[int, int] | None
    source_log: str
    raw_log: bytes
    raw_evidence_digest: str

    def require_complete(self, response: WorldInfoResponse) -> None:
        if self.ordered_sequence != WORLD_SEQUENCE:
            raise ValueError("Incomplete explicit world_info lifecycle evidence")
        replay = parse_world_info_evidence(
            self.raw_log, self.request_id, source_log=self.source_log
        )
        if (
            replay != self
            or self.request_id != response.request_id
            or self.dimensions_read != (response.map_width, response.map_height)
        ):
            raise ValueError("World-info internal/network evidence mismatch")


def parse_world_info_evidence(
    raw: bytes, request_id: str, *, source_log: str = "stderr.log"
) -> WorldInfoEvidence:
    validate_request_id(request_id)
    records = []
    dimensions = None
    for number, line in enumerate(raw.splitlines(keepends=True), 1):
        if not line.endswith(b"\n"):
            continue
        text = line.decode("utf-8", errors="strict").rstrip("\r\n")
        match = _NATIVE.fullmatch(text)
        if match is None:
            if "BRIDGE_" in text or "WORLD_INFO_" in text:
                raise ValueError("Malformed/non-native world_info marker")
            continue
        marker, suffix = match.groups()
        if len(records) >= len(WORLD_SEQUENCE) or marker != WORLD_SEQUENCE[len(records)]:
            raise ValueError("Duplicate/out-of-order world_info marker")
        expected = {
            "BRIDGE_STARTED": " protocol=1 api=15",
            "BRIDGE_REQUEST_RECEIVED": f" request_id={request_id} type=world_info protocol=1",
            "BRIDGE_RESPONSE_SENT": (
                f" request_id={request_id} type=world_info_result status=ok protocol=1"
            ),
            "BRIDGE_POST_RESPONSE_ALIVE": f" request_id={request_id}",
        }
        if marker == "WORLD_INFO_READ":
            read = _READ.fullmatch(suffix)
            if read is None or read[1] != request_id:
                raise ValueError("World-info read identity mismatch")
            dimensions = (validate_dimension(int(read[2])), validate_dimension(int(read[3])))
        elif suffix != expected[marker]:
            raise ValueError("World-info marker transaction mismatch")
        records.append(WorldInfoLogRecord(marker, number, text))
    return WorldInfoEvidence(
        request_id,
        tuple(r.marker for r in records),
        tuple(records),
        dimensions,
        source_log,
        raw,
        hashlib.sha256(raw).hexdigest(),
    )
