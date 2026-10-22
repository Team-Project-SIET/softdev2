"""One bounded native log, with explicit snapshot and final-file byte scopes."""

import hashlib

from app.simulation.openttd.tile_facts_evidence import GS_SEQUENCE, parse_tile_facts_evidence

POLICY = "terrain-execution-log-v1"
ARTIFACT = "stderr.log"
CAPTURE_BYTES = 262144


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def log_record(snapshot: bytes, final: bytes, request_id: str) -> dict:
    """Producer records the observed bytes, never a marker-search-derived endpoint."""
    record = dict(
        policy=POLICY,
        request_id=request_id,
        snapshot=dict(
            artifact=ARTIFACT,
            start_offset=0,
            end_offset=len(snapshot),
            byte_length=len(snapshot),
            sha256=_sha(snapshot),
            lifecycle_marker=GS_SEQUENCE[-1],
        ),
        final=dict(artifact=ARTIFACT, byte_length=len(final), sha256=_sha(final)),
    )
    verify_log_record(record, final, request_id)
    return record


def verify_log_record(record: dict, final: bytes, request_id: str) -> bytes:
    """Fail closed on wrong ranges, identities, final hash or ambiguous lifecycle."""
    try:
        if set(record) != {"policy", "request_id", "snapshot", "final"}:
            raise ValueError
        snapshot, whole = record["snapshot"], record["final"]
        if set(snapshot) != {
            "artifact",
            "start_offset",
            "end_offset",
            "byte_length",
            "sha256",
            "lifecycle_marker",
        } or set(whole) != {"artifact", "byte_length", "sha256"}:
            raise ValueError
        start, end, size = (snapshot[k] for k in ("start_offset", "end_offset", "byte_length"))
        if (
            record["policy"] != POLICY
            or record["request_id"] != request_id
            or snapshot["artifact"] != ARTIFACT
            or whole["artifact"] != ARTIFACT
            or any(type(n) is not int for n in (start, end, size, whole["byte_length"]))
            or start != 0
            or not 0 < end <= len(final) <= CAPTURE_BYTES
            or size != end - start
            or whole["byte_length"] != len(final)
            or whole["sha256"] != _sha(final)
            or snapshot["sha256"] != _sha(final[start:end])
            or snapshot["lifecycle_marker"] != GS_SEQUENCE[-1]
        ):
            raise ValueError
        selected = final[start:end]
        # Parse the whole log too: a repeated or later extra native request marker
        # cannot be hidden by choosing a valid earlier range.
        evidence = parse_tile_facts_evidence(selected, request_id)
        complete = parse_tile_facts_evidence(final, request_id)
        if evidence.ordered_sequence != GS_SEQUENCE or complete.suffixes != evidence.suffixes:
            raise ValueError
        return selected
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Invalid execution-log digest scope") from error
