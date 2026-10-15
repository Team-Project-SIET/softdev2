"""Immutable industry-production attempt identities and exact prelaunch predecessor lineage."""

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

KIND = "industry-production"
POLICY = "industry-production-attempt-lineage-v1"
PREFIX = "openttd-15.3-industry-production"
PRELAUNCH_STATES = {"PRELAUNCH_FAILED", "PREFLIGHT_FAILED"}


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict:
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError("Duplicate evidence field")
            result[k] = v
        return result

    value = json.loads(path.read_text(), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("Malformed attempt evidence")
    return value


def _files(directory: Path, exclude=()) -> dict[str, str]:
    result = {}
    for p in sorted(directory.rglob("*")):
        if p.is_symlink() or p.name == ".admin-secret":
            raise ValueError("Unsafe/private attempt evidence")
        if p.is_file() and p.name not in exclude:
            result[p.relative_to(directory).as_posix()] = file_digest(p)
    return result


def _manifest(files: dict[str, str]) -> str:
    return "".join(f"{h}  {p}\n" for p, h in sorted(files.items()))


@dataclass(frozen=True)
class AttemptIdentity:
    proof_kind: str
    freeze_revision: int
    attempt_id: str
    classification: str
    launches: int
    connections: int
    requests: int
    terminal_status: str
    evidence_directory: str
    evidence_manifest_digest: str
    evidence_digest: str
    revision_authority_digest: str
    parent_attempt_ids: tuple[str, ...] = ()


def read_attempt(directory: Path) -> AttemptIdentity:
    """Normalize legacy evidence without rewriting it; classify from activity/status."""
    try:
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("Missing predecessor evidence")
        files = _files(directory)
        manifest = directory / "artifact-manifest.sha256"
        if manifest.read_text() != _manifest(_files(directory, ("artifact-manifest.sha256",))):
            raise ValueError("Predecessor evidence manifest mismatch")
        candidates = [
            directory / n
            for n in ("PRELAUNCH-FAILURE.json", "proof-evidence.json")
            if (directory / n).is_file()
        ]
        if len(candidates) != 1:
            raise ValueError("Malformed/ambiguous predecessor evidence")
        record = _json(candidates[0])
        counts = []
        for k in ("launches", "connections", "requests"):
            value = record.get(k, record.get("requests_sent") if k == "requests" else None)
            if type(value) is not int or value < 0:
                raise ValueError("Exact integer activity counts required")
            counts.append(value)
        if "requests" in record and "requests_sent" in record:
            if type(record["requests_sent"]) is not int or record["requests_sent"] != counts[2]:
                raise ValueError("Contradictory application request counts")
        for flag in ("subprocess_created", "process_created", "attempt_executed"):
            if flag in record and type(record[flag]) is not bool:
                raise ValueError("Malformed process-creation evidence")
        status = record.get("state", record.get("status"))
        if not isinstance(status, str) or not any(s in status for s in ("FAIL", "SUCCESS")):
            raise ValueError("Terminal attempt evidence required")
        activity = (
            any(counts)
            or any(
                record.get(k) is True
                for k in ("subprocess_created", "process_created", "attempt_executed")
            )
            or "LAUNCHED" in record.get("states", [])
            or (directory / "process-launch.json").exists()
        )
        classification = "PRELAUNCH" if status in PRELAUNCH_STATES and not activity else "RUNTIME"
        if "preparation" in record:
            preparation = Path(record["preparation"])
            if not preparation.is_absolute():
                # Historical repository-relative records are resolved by their retained name.
                preparation = directory.parent / preparation.name
        else:
            name = directory.name.removesuffix("-gate-failure")
            preparation = directory.with_name(name)
        if preparation.parent.resolve() != directory.parent.resolve():
            raise ValueError("Predecessor preparation outside proof root")
        authority = preparation / "PRELAUNCH.json"
        meta = _json(authority)
        revision = meta.get("prelaunch_revision")
        if meta.get("mode") != KIND or type(revision) is not int or revision < 1:
            raise ValueError("Predecessor freeze identity invalid")
        evidence_digest = digest(files)
        attempt_id = (
            f"industry-production-v{revision}-{classification.lower()}-{evidence_digest[:16]}"
        )
        identity = AttemptIdentity(
            KIND,
            revision,
            attempt_id,
            classification,
            counts[0],
            counts[1],
            counts[2],
            status,
            directory.name,
            file_digest(manifest),
            evidence_digest,
            file_digest(authority),
        )
        modern = directory / "proof-attempt.json"
        if modern.exists():
            value = _json(modern)
            payload = _files(directory, ("artifact-manifest.sha256", "proof-attempt.json"))
            if value.get("payload_digest") != digest(payload):
                raise ValueError("Immutable attempt payload digest mismatch")
            if value.get("evidence_manifest_digest") != digest(payload):
                raise ValueError("Immutable attempt evidence manifest digest mismatch")
            if (
                value.get("proof_kind") != KIND
                or value.get("freeze_revision") != revision
                or value.get("classification") != classification
                or any(
                    value.get(k) != v
                    for k, v in zip(("launches", "connections", "requests"), counts, strict=True)
                )
            ):
                raise ValueError("Attempt identity contradicts observed evidence")
            if (
                value.get("attempt_id")
                != (
                    f"industry-production-v{revision}-{classification.lower()}-{digest(payload)[:16]}"
                )
                or value.get("terminal_status") != status
            ):
                raise ValueError("Attempt identity/status mismatch")
            parents = value.get("parent_attempt_ids")
            if not isinstance(parents, list) or parents != sorted(set(parents)):
                raise ValueError("Invalid attempt parent identities")
            identity = AttemptIdentity(
                KIND,
                revision,
                value["attempt_id"],
                classification,
                counts[0],
                counts[1],
                counts[2],
                status,
                directory.name,
                file_digest(manifest),
                evidence_digest,
                file_digest(authority),
                tuple(parents),
            )
        return identity
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("Malformed or missing predecessor evidence") from error


def relevant_failures(parent: Path) -> list[Path]:
    result = []
    for p in sorted(parent.iterdir()):
        if not p.is_dir():
            continue
        relevant = p.name.startswith(PREFIX) and (
            p.name.endswith("failure")
            or ("real-attempt" in p.name and p.name.rsplit("real-attempt", 1)[1].isdigit())
        )
        if not relevant and (p / "proof-attempt.json").exists():
            relevant = _json(p / "proof-attempt.json").get("proof_kind") == KIND
        if relevant:
            result.append(p)
    return result


def predecessor_row(directory: Path) -> dict:
    """Bind a stricter immutable postrun verdict without rewriting native evidence."""
    row = asdict(read_attempt(directory))
    analysis = directory.with_name(directory.name + "-postrun-verification")
    if analysis.exists():
        files = _files(analysis, ("artifact-manifest.sha256",))
        if (analysis / "artifact-manifest.sha256").read_text() != _manifest(files):
            raise ValueError("Postrun failure manifest mismatch")
        result = _json(analysis / "post-cleanup-integrity.json")
        authority = _json(directory / "PRELAUNCH.json")
        native = _json(directory / "proof-evidence.json")
        if (
            native.get("retries") != 0
            or native.get("reconnects") != 0
            or result.get("overall_acceptance") != "FAILED"
            or result.get("source_hashes_exact") is not False
            or result.get("attempt_manifest_exact") is not True
            or result.get("protected_historical_hashes_exact") is not True
            or result.get("context_unchanged") is not True
            or (row["launches"], row["connections"], row["requests"]) != (1, 1, 1)
            or result.get("request_digest") != authority["request_sha256"]
            or not result.get("reason")
        ):
            raise ValueError("Contradictory post-launch failure authority")
        row.update(
            classification="POST_LAUNCH_FAILURE",
            terminal_status="FAILED_POSTRUN_INTEGRITY",
            terminal_failure_reason=result["reason"],
            authorized_attempt_id=authority["attempt_id"],
            postrun_evidence_directory=analysis.name,
            postrun_manifest_digest=file_digest(analysis / "artifact-manifest.sha256"),
            postrun_report_digest=file_digest(analysis / "final-report.md"),
            postrun_integrity_digest=file_digest(analysis / "post-cleanup-integrity.json"),
            native_terminal_status=row["terminal_status"],
            retries=0,
            reconnects=0,
        )
    return row


def capture_lineage(directory: Path, revision: int, destination: Path) -> dict:
    predecessors = [predecessor_row(p) for p in relevant_failures(directory.parent)]
    predecessors.sort(key=lambda item: item["attempt_id"])
    launches = sum(r["launches"] for r in predecessors)
    attempt = launches + 1
    value = dict(
        policy=POLICY,
        proof_kind=KIND,
        freeze_revision=revision,
        attempt_id=f"industry-production-v{revision}-native-attempt{attempt}",
        attempt_number=attempt,
        evidence_directory=destination.name,
        supersedes_prelaunch_attempts=[
            r for r in predecessors if r["classification"] == "PRELAUNCH"
        ],
        post_launch_predecessors=[r for r in predecessors if r["classification"] != "PRELAUNCH"],
        continuation="NEW_RUNTIME_ATTEMPT" if launches else "PRELAUNCH_CONTINUATION",
        prelaunch_continuation_exception_used=not bool(launches) and bool(predecessors),
        fresh_explicit_authorization_required=True,
    )
    value["lineage_digest"] = digest(value)
    validate_lineage(directory, value, revision, destination)
    return value


def lineage_rows(value):
    return sorted(
        value["supersedes_prelaunch_attempts"] + value["post_launch_predecessors"],
        key=lambda r: r["attempt_id"],
    )


def validate_lineage(directory: Path, value: dict, revision: int, destination: Path) -> int:
    """Execution gate: historical identity plus complete current consumed history."""
    if destination.exists() or destination.is_symlink():
        raise ValueError(
            "Attempt destination already consumed; exact new attempt destination required"
        )
    count = validate_historical_lineage(directory, value, revision, destination)
    rows = lineage_rows(value)
    names = [r["evidence_directory"] for r in rows]
    observed = {p.name for p in relevant_failures(directory.parent)}
    if set(names) != observed:
        raise ValueError("Unknown, unacknowledged, or missing predecessor failure")
    return count


def validate_historical_lineage(
    directory: Path, value: dict, revision: int, destination: Path
) -> int:
    """Validate frozen predecessor identities without discovering later attempts."""
    try:
        rows = lineage_rows(value)
        launches = sum(r["launches"] for r in rows)
        attempt = launches + 1
        if (
            value["policy"] != POLICY
            or value["proof_kind"] != KIND
            or value["freeze_revision"] != revision
            or value["evidence_directory"] != destination.name
            or value["attempt_number"] != attempt
            or value["attempt_id"] != f"industry-production-v{revision}-native-attempt{attempt}"
            or value["fresh_explicit_authorization_required"] is not True
            or value["continuation"]
            != ("NEW_RUNTIME_ATTEMPT" if launches else "PRELAUNCH_CONTINUATION")
            or value["prelaunch_continuation_exception_used"] != (not bool(launches) and bool(rows))
            or value["lineage_digest"]
            != digest({k: v for k, v in value.items() if k != "lineage_digest"})
        ):
            raise ValueError("Frozen lineage identity/destination mismatch")
        if launches and destination.name != f"{PREFIX}-real-attempt{attempt}":
            raise ValueError("Post-launch failure requires exact new attempt destination")
        ids = [r["attempt_id"] for r in rows]
        names = [r["evidence_directory"] for r in rows]
        if ids != sorted(set(ids)) or len(set(names)) != len(names):
            raise ValueError("Duplicate or noncanonical predecessor identity")
        for row in rows:
            name = row["evidence_directory"]
            if Path(name).name != name:
                raise ValueError("Unsafe predecessor path")
            current = json.loads(json.dumps(predecessor_row(directory.parent / name)))
            if current != json.loads(json.dumps(row)):
                raise ValueError("Predecessor evidence identity/digest mismatch")
            if row in value["supersedes_prelaunch_attempts"]:
                if current["classification"] != "PRELAUNCH" or any(
                    current[k] != 0 for k in ("launches", "connections", "requests")
                ):
                    raise ValueError("Runtime failure cannot use prelaunch continuation")
            elif (
                current["classification"] not in ("RUNTIME", "POST_LAUNCH_FAILURE")
                or current["launches"] != 1
                or not any(mark in current["terminal_status"] for mark in ("FAIL", "SUCCESS"))
            ):
                raise ValueError(
                    "Consumed terminal post-launch predecessor required for new attempt"
                )
            if revision <= current["freeze_revision"]:
                raise ValueError("Newer freeze required; same-freeze reauthorization forbidden")
        return len(rows)
    except (KeyError, TypeError) as error:
        raise ValueError("Malformed frozen lineage") from error


def retain_attempt_identity(directory: Path, metadata: dict, result: dict) -> None:
    """A terminal identity binds public payload files; the final manifest binds this record."""
    counts = tuple(
        result.get(k, result.get("requests_sent", 0))
        for k in ("launches", "connections", "requests")
    )
    status = result.get("state", result.get("status"))
    classification = (
        "PRELAUNCH" if status in PRELAUNCH_STATES and counts == (0, 0, 0) else "RUNTIME"
    )
    payload_digest = digest(_files(directory, ("artifact-manifest.sha256", "proof-attempt.json")))
    revision = metadata["prelaunch_revision"]
    record = dict(
        proof_kind=KIND,
        freeze_revision=revision,
        attempt_id=f"industry-production-v{revision}-{classification.lower()}-{payload_digest[:16]}",
        classification=classification,
        launches=counts[0],
        connections=counts[1],
        requests=counts[2],
        terminal_status=status,
        evidence_directory=directory.name,
        payload_digest=payload_digest,
        evidence_manifest_digest=payload_digest,
        parent_attempt_ids=metadata.get("predecessor_attempt_ids", []),
    )
    with (directory / "proof-attempt.json").open("x") as stream:
        stream.write(json.dumps(record, sort_keys=True, indent=2) + "\n")
