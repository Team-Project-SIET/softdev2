"""Immutable preparation, separately bound authorization, and one-shot consumption.

No operator authorization issuer exists here. Production verification therefore
fails closed; an injected authority is only a controlled validation seam.
"""

import json
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from .harness import manifest, sha256, write_json
from .terrain_preparation import TerrainCandidate, budget, load_terrain_prepared

ACCEPTANCE = (
    "source_integrity",
    "exact_runtime",
    "one_continuous_secure_connection",
    "one_exact_request",
    "correlated_receipt",
    "payload_bound",
    "native_read_evidence",
    "post_yield_liveness",
    "exact_row_major_coverage",
    "accounting",
    "child_reaped",
    "endpoint_cleanup",
    "post_run_integrity",
)
CLEANUP = ("graceful_quit", "child_reaped", "linux_endpoint_verification", "owned_cache_disposal")


def validate_seal_record(directory: Path, destination: Path):
    if directory != directory.resolve() or destination != destination.resolve():
        raise ValueError("Nonaliasing seal and destination required")
    record = json.loads((directory / "PRELAUNCH.json").read_text())
    if (
        record.get("state") != "SEALED_UNAUTHORIZED"
        or record.get("authorization_policy", "INDEPENDENTLY_AUTHENTICATED_PROOF")
        not in ("OPERATOR_ATTENDED_LOCAL_PROOF", "INDEPENDENTLY_AUTHENTICATED_PROOF")
        or type(record.get("maximum_launches", 1)) is not int
        or record.get("maximum_launches", 1) != 1
        or record.get("authorized_one_launch") is not False
        or record.get("attempt_state") != "RESERVED"
        or record.get("attempt_directory") != str(destination)
        or record.get("budget") != budget()
        or record.get("acceptance") != list(ACCEPTANCE)
        or record.get("cleanup") != list(CLEANUP)
        or not str(record.get("attempt_identity", "")).startswith("terrain-single-page-")
    ):
        raise PermissionError("Immutable seal contract mismatch")
    if (directory / "SEAL.sha256").read_text() != sha256(directory / "PRELAUNCH.json") + "\n":
        raise ValueError("Immutable seal digest mismatch")
    if directory.stat().st_mode & 0o222 or any(
        p.is_symlink() or p.stat().st_mode & 0o222 for p in directory.iterdir()
    ):
        raise ValueError("Seal must be read-only and nonaliasing")
    return record


def validate_authorization(directory: Path, destination: Path, authorization, *, authority=None):
    """Validate exact binding and issuer provenance, never issue permission.

    Native callers never inject an authority. Until an operator approval issuer
    is established, the production boundary rejects even a well-shaped artifact.
    """
    record = validate_seal_record(directory, destination)
    from .terrain_attempt import validate_immutable_seal

    prepared = load_terrain_prepared(Path(record["candidate_path"]), directory)
    validate_immutable_seal(prepared, destination)
    expected = dict(
        seal_sha256=sha256(directory / "PRELAUNCH.json"),
        attempt_identity=record["attempt_identity"],
        attempt_directory=str(destination),
        authorized_launch_count=1,
    )
    from .terrain_authorization import OneLaunchAuthorization

    approval = OneLaunchAuthorization.from_mapping(authorization)
    if any(approval.to_mapping()[k] != v for k, v in expected.items()):
        raise PermissionError("Missing/invalid exact-seal authorization")
    if destination.exists():
        raise PermissionError("Attempt already claimed; authorization cannot be replayed")
    if authority is None:
        raise PermissionError("Trusted operator authorization issuer is not configured")
    if authority(authorization) is not True:
        raise PermissionError("Operator approval provenance rejected")
    return expected


def consume_authorized_attempt(
    directory: Path, destination: Path, authorization, *, authority=None
):
    """Atomic one-shot claim after authorization; failure keeps the claim/evidence."""
    from .terrain_authorization import LocalOperatorAuthorization

    if isinstance(authorization, LocalOperatorAuthorization):
        if authority is not None:
            raise PermissionError("Model A cannot use an independent/test issuer callback")
        return _acquire_local_claim(directory, destination, authorization)
    binding = validate_authorization(directory, destination, authorization, authority=authority)
    # mkdir is the exclusive cross-process claim; its existence alone burns the
    # attempt even when writing the record or post-claim integrity fails.
    destination.mkdir(mode=0o700)
    _fsync_directory(destination.parent)
    write_json(
        destination / "authorization-consumed.json",
        dict(
            **binding,
            state="STARTED",
            mode="CONTROLLED_AUTHORITY_VALIDATION",
            authorization_id=authorization["authorization_id"],
            issuer_id=authorization["issuer_id"],
        ),
    )
    with (destination / "authorization-consumed.json").open("rb") as stream:
        os.fsync(stream.fileno())
    _fsync_directory(destination)
    # Close the validation/acquisition gap without releasing a failed claim.
    record = validate_seal_record(directory, destination)
    from .terrain_attempt import validate_immutable_seal

    prepared = load_terrain_prepared(Path(record["candidate_path"]), directory)
    validate_immutable_seal(prepared, destination)
    return binding


def _fsync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def seal_candidate(
    candidate: TerrainCandidate,
    directory: Path,
    destination: Path,
    *,
    authorization_policy="INDEPENDENTLY_AUTHENTICATED_PROOF",
):
    """Atomically publish one read-only unauthorized seal after full preflight."""
    if authorization_policy not in (
        "OPERATOR_ATTENDED_LOCAL_PROOF",
        "INDEPENDENTLY_AUTHENTICATED_PROOF",
    ):
        raise ValueError("Unsupported authorization policy")
    candidate.preflight()
    if (
        "authorization_policy" in candidate.record
        and candidate.record["authorization_policy"] != authorization_policy
    ):
        raise PermissionError("Explicit candidate/seal authorization policy mismatch")
    directory, destination = directory.absolute(), destination.absolute()
    if (
        directory != directory.resolve()
        or destination != destination.resolve()
        or directory.exists()
        or destination.exists()
        or directory == destination
        or directory in destination.parents
        or destination in directory.parents
        or directory.is_relative_to(Path(candidate.record["workspace"]))
        or destination.is_relative_to(Path(candidate.record["workspace"]))
    ):
        raise ValueError("Fresh separate persistent seal/attempt roots required")
    from .ownership import build_ownership

    directory.parent.mkdir(parents=True, exist_ok=True)
    stage = directory.with_name(directory.name + ".staging-" + uuid.uuid4().hex)
    stage.mkdir(mode=0o700)
    row = candidate.record
    frozen = dict(row["source_integrity"])
    frozen[str(candidate.directory / "CANDIDATE.json")] = sha256(
        candidate.directory / "CANDIDATE.json"
    )
    try:
        from .terrain_retention import INDEX, retain_inputs

        retained = retain_inputs(candidate, stage)
        frozen[str(directory / INDEX)] = sha256(stage / INDEX)
        for item in retained["entries"]:
            frozen[str(directory / item["artifact"])] = item["sha256"]
        for name in ("request.json", "historical-integrity.json", "runtime-materializations.json"):
            shutil.copyfile(candidate.directory / name, stage / name)
            frozen[str(directory / name)] = sha256(stage / name)
        graph = build_ownership(
            directory,
            Path(row["workspace"]),
            Path(row["key_path"]),
            destination,
            {**frozen, str(directory / "PRELAUNCH.json"): "", str(directory / "SEAL.sha256"): ""},
            {},
            capture_outputs=tuple(Path(p) for p in row["capture_outputs"]),
        )
        write_json(stage / "path-ownership.json", graph.public())
        frozen[str(directory / "path-ownership.json")] = sha256(stage / "path-ownership.json")
        record = dict(
            state="SEALED_UNAUTHORIZED",
            authorization_policy=authorization_policy,
            authorized_one_launch=False,
            maximum_launches=1,
            attempt_state="RESERVED",
            attempt_identity="terrain-single-page-" + uuid.uuid4().hex,
            attempt_directory=str(destination),
            mode="terrain-single-page",
            candidate_path=str(candidate.directory),
            candidate_sha256=sha256(candidate.directory / "CANDIDATE.json"),
            canonical_inputs_sha256=sha256(stage / INDEX),
            ownership_sha256=sha256(stage / "path-ownership.json"),
            execution_log_policy="terrain-execution-log-v1",
            argv=row["argv"],
            environment=row["environment"],
            environment_allowlist=row["environment_allowlist"],
            executable_digest=row["executable_digest"],
            graphics_digest=row["graphics_digest"],
            bridge_digest=row["bridge_digest"],
            source_digest=row["source_digest"],
            configuration_digest=row["configuration_digest"],
            request_sha256=row["request_sha256"],
            region=row["region"],
            expected_tiles=row["expected_tiles"],
            cursor=0,
            source=row["source"],
            budget=budget(),
            acceptance=list(ACCEPTANCE),
            cleanup=list(CLEANUP),
            endpoints=row["endpoints"],
            game_port=row["endpoints"][0],
            admin_port=row["endpoints"][1],
            public_key=row["public_key"],
            historical_integrity_sha256=sha256(stage / "historical-integrity.json"),
            historical_base=row["historical_base"],
        )
        write_json(stage / "PRELAUNCH.json", record)
        frozen[str(directory / "PRELAUNCH.json")] = sha256(stage / "PRELAUNCH.json")
        (stage / "SEAL.sha256").write_text(sha256(stage / "PRELAUNCH.json") + "\n")
        frozen[str(directory / "SEAL.sha256")] = sha256(stage / "SEAL.sha256")
        write_json(stage / "source-freeze.json", dict(sorted(frozen.items())))
        (stage / "artifact-manifest.sha256").write_text(manifest(stage))
        for p in stage.rglob("*"):
            if p.is_dir():
                continue
            with p.open("rb") as stream:
                os.fsync(stream.fileno())
            p.chmod(0o444)
        for p in sorted(stage.rglob("*"), reverse=True):
            if p.is_dir():
                _fsync_directory(p)
                p.chmod(0o555)
        _fsync_directory(stage)
        stage.chmod(0o555)
        # Atomic publication, no replacement: reserve the final name exclusively.
        # rename cannot safely reject an empty competing directory; use renameat2.
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        if libc.renameat2(-100, os.fsencode(stage), -100, os.fsencode(directory), 1) != 0:
            raise OSError(ctypes.get_errno(), "Exclusive seal publication failed")
        fd = os.open(directory.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        from .terrain_attempt import validate_immutable_seal

        prepared = load_terrain_prepared(candidate.directory, directory)
        validate_immutable_seal(prepared, destination)
        if json.loads((directory / "PRELAUNCH.json").read_text()) != record:
            raise ValueError("Seal reread differs")
        return prepared
    except BaseException:
        # Retain failed staging/publication; never substitute a second seal.
        raise


@dataclass(frozen=True)
class AttemptClaim:
    destination: Path
    record_sha256: str


def _local_claim_record(authorization):
    return dict(authorization.public_record(), state="STARTED", no_retry=True)


def validate_local_authorization(prepared, destination, authorization, *, native, claim=None):
    from .terrain_authorization import LOCAL_POLICY, FailureCode, LocalProofFailure

    authorization.require_process(native=native)
    row = validate_seal_record(prepared.directory, destination)
    if (
        row.get("authorization_policy") != LOCAL_POLICY
        or authorization.seal_sha256 != sha256(prepared.directory / "PRELAUNCH.json")
        or authorization.attempt_identity != row["attempt_identity"]
        or authorization.attempt_directory != str(destination)
    ):
        raise LocalProofFailure(
            FailureCode.AUTHORIZATION_INVALID, "Exact local seal binding mismatch"
        )
    if claim is None:
        if destination.exists():
            raise LocalProofFailure(FailureCode.ATTEMPT_ALREADY_CONSUMED, "No retry/resume")
        return
    validate_local_claim(destination, authorization, claim)


def validate_local_claim(destination, authorization, claim):
    from .terrain_authorization import FailureCode, LocalProofFailure

    path = destination / "authorization-consumed.json"
    try:
        if (
            not isinstance(claim, AttemptClaim)
            or claim.destination != destination
            or destination != destination.resolve()
            or path.is_symlink()
            or destination.stat().st_uid != os.getuid()
            or destination.stat().st_mode & 0o777 != 0o700
            or path.stat().st_uid != os.getuid()
            or sha256(path) != claim.record_sha256
            or json.loads(path.read_text()) != _local_claim_record(authorization)
            or any(
                p.name
                not in (
                    "authorization-consumed.json",
                    "launch-claim.json",
                    "native-launch-claimed.json",
                )
                for p in destination.iterdir()
            )
        ):
            raise ValueError("Claim mismatch or completed/foreign attempt")
    except (ValueError, OSError) as error:
        raise LocalProofFailure(
            FailureCode.AUTHORIZATION_INVALID, "Exact in-flight claim required"
        ) from error


def _acquire_local_claim(directory, destination, authorization):
    from .terrain_attempt import validate_immutable_seal
    from .terrain_authorization import FailureCode, LocalProofFailure, LocalTrust

    prepared = load_terrain_prepared(
        Path(json.loads((directory / "PRELAUNCH.json").read_text())["candidate_path"]), directory
    )
    native = authorization.trust == LocalTrust.LOCAL_OPERATOR_ATTESTED
    validate_immutable_seal(prepared, destination)
    validate_local_authorization(prepared, destination, authorization, native=native)
    try:
        destination.mkdir(mode=0o700)
    except FileExistsError as error:
        raise LocalProofFailure(
            FailureCode.ATTEMPT_ALREADY_CONSUMED, "Exclusive claim lost"
        ) from error
    except OSError as error:
        raise LocalProofFailure(
            FailureCode.CLAIM_ACQUISITION_FAILED, "Cannot acquire attempt"
        ) from error
    try:
        _fsync_directory(destination.parent)
        write_json(destination / "authorization-consumed.json", _local_claim_record(authorization))
        with (destination / "authorization-consumed.json").open("rb") as stream:
            os.fsync(stream.fileno())
        _fsync_directory(destination)
        claim = AttemptClaim(destination, sha256(destination / "authorization-consumed.json"))
        validate_immutable_seal(prepared, destination)
        validate_local_authorization(
            prepared, destination, authorization, native=native, claim=claim
        )
        return claim
    except Exception as error:
        # The acquired directory remains consumed even if recording/fsync fails.
        failure = destination / "claim-failure.json"
        if not failure.exists():
            write_json(failure, dict(stage="CLAIM_ACQUISITION_FAILED", error=type(error).__name__))
        raise
