"""Explicit GameScript-origin lifecycle records, independent of the network ACK."""

import hashlib
import re
from dataclasses import dataclass

SEQUENCE = (
    "BRIDGE_STARTED",
    "BRIDGE_REQUEST_RECEIVED",
    "BRIDGE_ACK_SENT",
    "BRIDGE_POST_ACK_ALIVE",
)
# Native 15.3 ScriptLog::Info -> Debug(script, 4, "[root] [I] message").
NATIVE_RECORD = re.compile(
    r"(?:\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\] )?"
    r"dbg: \[script:4\] \[(\d+)\] \[I\] (BRIDGE_[A-Z_]+)(.*)"
)


@dataclass(frozen=True)
class GameScriptLogRecord:
    marker: str
    line_number: int
    raw_line: str
    root_company: int


@dataclass(frozen=True)
class GameScriptProofEvidence:
    startup_observed: bool
    startup_marker: str | None
    request_received: bool
    request_id: str
    ack_sent: bool
    post_ack_alive: bool
    ordered_sequence: tuple[str, ...]
    source_log: str
    records: tuple[GameScriptLogRecord, ...]
    raw_evidence_digest: str
    protocol: int = 1
    request_type: str = "ping"
    ack_type: str = "ack"
    ack_status: str = "ok"
    semantic_identity_basis: str = "Frozen bridge validated ping and fixed successful ACK path"

    def require_complete(self) -> None:
        if (
            self.ordered_sequence != SEQUENCE
            or tuple(r.marker for r in self.records) != SEQUENCE
            or not all(
                (self.startup_observed, self.request_received, self.ack_sent, self.post_ack_alive)
            )
        ):
            raise ValueError("Incomplete explicit GameScript lifecycle evidence")
        numbers = [r.line_number for r in self.records]
        if numbers != sorted(set(numbers)) or numbers[0] < 1:
            raise ValueError("GameScript supporting records are not independently ordered")
        replay = parse_gamescript_evidence(
            "".join(r.raw_line + "\n" for r in self.records).encode(), self.request_id
        )
        if replay.ordered_sequence != SEQUENCE:
            raise ValueError("GameScript records do not support their semantic markers")


def parse_gamescript_evidence(
    raw: bytes, request_id: str, *, source_log: str = "stderr.log"
) -> GameScriptProofEvidence:
    """Parse complete newline-terminated native records; fail closed on bad markers.

    Prefix validation prevents Python/stdout console text from being substituted.
    The digest covers the exact entire captured log, including irrelevant records.
    Partial evidence is retained on failure, but can never satisfy require_complete.
    """
    records = []
    for number, line in enumerate(raw.splitlines(keepends=True), 1):
        if not line.endswith(b"\n"):
            continue  # A concurrently written partial record is not observable evidence yet.
        text = line.decode("utf-8", errors="strict").rstrip("\r\n")
        match = NATIVE_RECORD.fullmatch(text)
        if match is None:
            if "BRIDGE_" in text:
                raise ValueError("Malformed/non-native bridge evidence")
            continue
        root, marker, suffix = match.groups()
        # 15.3 company_type.h OWNER_DEITY = 0x12; GameInstance::Initialize root.
        if int(root) != 18:
            raise ValueError("Marker did not originate from the GameScript root")
        if len(records) >= len(SEQUENCE) or marker != SEQUENCE[len(records)]:
            raise ValueError("Duplicate or out-of-order bridge marker")
        expected = " protocol=1 api=15" if not records else f" request_id={request_id}"
        if suffix != expected:
            raise ValueError("Bridge protocol/API/request identity mismatch")
        if records and int(root) != records[0].root_company:
            raise ValueError("Bridge instance identity changed")
        records.append(GameScriptLogRecord(marker, number, text, int(root)))
    sequence = tuple(record.marker for record in records)
    return GameScriptProofEvidence(
        bool(records),
        records[0].raw_line if records else None,
        len(records) >= 2,
        request_id,
        len(records) >= 3,
        len(records) == 4,
        sequence,
        source_log,
        tuple(records),
        hashlib.sha256(raw).hexdigest(),
    )
