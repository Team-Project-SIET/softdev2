"""One-shot terrain acceptance on the existing proof backend/cleanup seam."""

import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.simulation.openttd.tile_facts import TileFactsRequest
from app.simulation.openttd.tile_facts_evidence import parse_tile_facts_evidence

from .attempt import Gate, Gates
from .endpoints import verify_cleanup_endpoints
from .harness import (
    PROJECT,
    EndpointReservation,
    launch_argv,
    manifest,
    sha256,
    verify_freeze,
    write_json,
)
from .terrain_preparation import REQUEST, budget, source_freeze


def _validate_prelaunch_integrity(
    prepared, destination: Path, *, native: bool, capture_phase="absent"
):
    """A candidate is never a launch seal. The operator must supply a reviewed seal."""
    record = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
    if destination.is_relative_to(prepared.spec.workspace.root):
        raise ValueError("Fresh persistent attempt destination required")
    if record.get("mode") != "terrain-single-page" or prepared.request != REQUEST:
        raise ValueError("Dedicated single-page preparation required")
    if record.get("attempt_directory") != str(destination) or record.get("budget") != budget():
        raise ValueError("Attempt/budget identity mismatch")
    if native and (
        record.get("state") != "SEALED_UNAUTHORIZED"
        or record.get("authorized_one_launch") is not False
    ):
        raise PermissionError("Candidate is not an immutable unauthorized seal")
    if not native and record.get("state") != "CONTROLLED_FAKE_PRELAUNCH":
        raise ValueError("Controlled tests require controlled preparation")
    frozen = json.loads((prepared.directory / "source-freeze.json").read_text())
    verify_freeze(frozen)
    if native:
        from .historical_protection import explicit_protection_base, validate_protection
        from .ownership import validate_ownership
        from .terrain_preparation import TerrainCandidate, package_bytes, package_digest

        candidate_path = Path(record["candidate_path"])
        candidate_record = json.loads((candidate_path / "CANDIDATE.json").read_text())
        TerrainCandidate(candidate_path, candidate_record).preflight(capture_phase=capture_phase)
        for field in (
            "historical_base",
            "argv",
            "environment",
            "environment_allowlist",
            "executable_digest",
            "graphics_digest",
            "bridge_digest",
            "source_digest",
            "configuration_digest",
            "request_sha256",
            "region",
            "expected_tiles",
            "cursor",
            "source",
            "endpoints",
            "public_key",
        ):
            if record.get(field) != candidate_record[field]:
                raise ValueError("Seal/candidate identity mismatch: " + field)
        if any(frozen.get(p) != h for p, h in candidate_record["source_integrity"].items()):
            raise ValueError("Final freeze omits reviewed candidate source identity")
        if record.get("candidate_sha256") != sha256(candidate_path / "CANDIDATE.json"):
            raise ValueError("Reviewed candidate changed")
        history = json.loads((prepared.directory / "historical-integrity.json").read_text())
        validate_protection(explicit_protection_base(history, PROJECT), history)
        if prepared.spec.argv != launch_argv(
            prepared.spec.identity.executable, prepared.spec.workspace.config, prepared.endpoints[0]
        ):
            raise ValueError("Exact launch specification mismatch")
        if dict(prepared.spec.environment) != dict(prepared.spec.workspace.environment):
            raise ValueError("Environment allowlist mismatch")
        package = {
            n: (prepared.spec.workspace.game / "NoMutationBridge" / n).read_bytes()
            for n in package_bytes()
        }
        if (
            package != package_bytes()
            or package_digest(package) != candidate_record["bridge_digest"]
        ):
            raise ValueError("Runtime package differs from reviewed terrain package")
        config = prepared.spec.workspace.config.read_text()
        private = (prepared.spec.workspace.root / "private.cfg").read_text()
        secrets = (prepared.spec.workspace.root / "secrets.cfg").read_text()
        if (
            "allow_insecure_admin_login = false" not in config
            or "admin_password = \n" not in secrets
            or prepared.public_key not in private
        ):
            raise ValueError("Secure Admin configuration mismatch")
        if frozen.get(str(candidate_path / "CANDIDATE.json")) != record.get("candidate_sha256"):
            raise ValueError("Reviewed candidate not retained in frozen input inventory")

        if "canonical_inputs_sha256" in record:
            from .terrain_retention import verify_inputs

            verify_inputs(prepared.directory, record, frozen)

        validate_ownership(prepared, frozen)
        if (prepared.directory / "artifact-manifest.sha256").read_text() != manifest(
            prepared.directory
        ):
            raise ValueError("Final immutable preparation manifest mismatch")
        if any(frozen.get(p) != h for p, h in source_freeze().items()):
            raise ValueError("Incomplete runtime-critical source inventory")
        if frozen.get(str(prepared.directory / "PRELAUNCH.json")) != sha256(
            prepared.directory / "PRELAUNCH.json"
        ):
            raise ValueError("Launch seal not frozen")
    if (prepared.directory / "request.json").read_bytes() != REQUEST.to_bytes():
        raise ValueError("Request bytes changed")
    return frozen


def validate_immutable_seal(prepared, destination: Path, *, capture_phase="absent"):
    """Integrity only; this read-only operation never authorizes or consumes."""
    from .terrain_seal import validate_seal_record

    validate_seal_record(prepared.directory, destination)
    return _validate_prelaunch_integrity(
        prepared, destination, native=True, capture_phase=capture_phase
    )


def validate_final_prelaunch(
    prepared,
    destination: Path,
    *,
    native: bool,
    authorization=None,
    claim=None,
    capture_phase="absent",
):
    """Launch gate: an immutable unauthorized seal is necessary but insufficient."""
    from .terrain_authorization import (
        LOCAL_POLICY,
        FailureCode,
        LocalOperatorAuthorization,
        LocalProofFailure,
    )

    local = isinstance(authorization, LocalOperatorAuthorization)
    seal_path = prepared.directory / "PRELAUNCH.json"
    policy = json.loads(seal_path.read_text()).get("authorization_policy")
    if policy == LOCAL_POLICY and not local:
        raise LocalProofFailure(
            FailureCode.AUTHORIZATION_INVALID, "Local attended confirmation required"
        )
    if not native and not local:
        return _validate_prelaunch_integrity(prepared, destination, native=False)
    if local:
        from .terrain_seal import validate_seal_record

        try:
            validate_seal_record(prepared.directory, destination)
        except (ValueError, OSError, PermissionError) as error:
            raise LocalProofFailure(FailureCode.SEAL_INVALID, str(error)) from error
        try:
            frozen = validate_immutable_seal(prepared, destination, capture_phase=capture_phase)
        except (ValueError, OSError, PermissionError) as error:
            raise LocalProofFailure(FailureCode.SOURCE_INTEGRITY_FAILED, str(error)) from error
    else:
        frozen = validate_immutable_seal(prepared, destination, capture_phase=capture_phase)
    from .terrain_seal import validate_authorization

    if local:
        from .terrain_seal import validate_local_authorization

        validate_local_authorization(
            prepared, destination, authorization, native=native, claim=claim
        )
    else:
        validate_authorization(prepared.directory, destination, authorization)
    return frozen


def verify_page(exchange, raw, width, height):
    exchange.validate()
    if (
        exchange.request_payload != REQUEST.to_bytes()
        or len(exchange.response_payload) > budget()["response_bytes"]
    ):
        raise ValueError("Frozen request/response bound mismatch")
    response = exchange.response
    if exchange.response_payload != response.to_bytes():
        raise ValueError("Native canonical serializer mismatch")
    q = TileFactsRequest.parse(exchange.request_payload)
    q.require_map(width, height)
    if (response.map_width, response.map_height) != (width, height) or (width, height) != (64, 64):
        raise ValueError("Independent welcome/map identity mismatch")
    if (
        response.region != q.region
        or response.cursor != 0
        or response.has_more
        or response.next_cursor is not None
    ):
        raise ValueError("Exact single-page region required")
    if tuple(r[0] for r in response.rows) != (65, 66, 67, 68, 69):
        raise ValueError("Incomplete/incorrect row-major coverage")
    evidence = parse_tile_facts_evidence(raw, q.request_id)
    evidence.require_complete(exchange)
    return dict(
        schema_valid=True,
        coverage_valid=True,
        native_read_evidence=True,
        post_yield_liveness=True,
        response_sha256=exchange.receipt.response_payload_sha256,
        evidence_sha256=evidence.raw_digest,
    )


async def execute_single_page(prepared, backend, destination: Path, *, authorization=None):
    """No retry/resume. Failures remain bounded and cleanup gates are independent."""
    if destination.exists():
        raise ValueError("Attempt already claimed; no retry")
    native = backend.kind == "REAL"
    if backend.kind not in ("REAL", "CONTROLLED"):
        raise ValueError("Unknown backend trust")
    # Read-only before claim; failures here do not consume native attempts.
    frozen = validate_final_prelaunch(
        prepared, destination, native=native, authorization=authorization
    )
    backend.preflight(prepared)
    reservation = EndpointReservation.allocate(*prepared.endpoints) if native else None
    result: dict[str, Any] = dict(
        mode=backend.kind,
        status=backend.kind + "_FAILED",
        launches=0,
        connections=0,
        requests=0,
        retries=0,
        error=None,
        gates={},
    )
    from .terrain_authorization import LocalOperatorAuthorization

    local = isinstance(authorization, LocalOperatorAuthorization)
    claim = None
    try:
        if local:
            from .terrain_seal import consume_authorized_attempt

            claim = consume_authorized_attempt(prepared.directory, destination, authorization)
        else:
            destination.mkdir(mode=0o700)  # Existing controlled/legacy claim.
    except BaseException:
        if reservation is not None:
            reservation.close()
        raise
    exchange = None
    evidence_snapshot = None
    cleanup = {}
    gates = Gates()
    try:
        write_json(
            destination / "launch-claim.json",
            dict(
                mode=backend.kind,
                prepared_directory=str(prepared.directory),
                request_sha256=sha256(prepared.directory / "request.json"),
                no_retry=True,
            ),
        )
        if local:
            backend.bind_authorization(authorization, claim)
        verify_freeze(frozen)
        if reservation is not None:
            reservation.close()
        await backend.launch(prepared)
        if local and not native:
            assert claim is not None
            write_json(
                destination / "controlled-launch-claimed.json",
                dict(
                    mode="CONTROLLED",
                    launch_invocations=1,
                    no_retry=True,
                    seal_sha256=authorization.seal_sha256,
                    attempt_identity=authorization.attempt_identity,
                    owner_nonce=authorization.owner_nonce,
                    owner_pid=authorization.owner_pid,
                    owner_start=authorization.owner_start,
                    consumed_record_sha256=claim.record_sha256,
                ),
            )
        result["launches"] = backend.launches
        gates.advance(Gate.PROCESS)
        backend.failure_stage = "authentication"
        auth = await backend.authenticate(prepared, gates)
        result["connections"] = backend.connections
        write_json(destination / "authentication.json", auth)
        write_json(
            destination / "source-identities.json",
            dict(
                source_integrity=frozen, request_sha256=sha256(prepared.directory / "request.json")
            ),
        )
        backend.failure_stage = "setup"
        await backend.setup(prepared)
        gates.advance(Gate.SUBSCRIPTION)
        gates.advance(Gate.BRIDGE_STARTED)
        backend.accounting.enter("query")
        backend.failure_stage = "tile_facts_page"
        exchange = await backend.tile_facts_page(prepared.request)
        if len(exchange.response_payload) > budget()["response_bytes"]:
            write_json(
                destination / "failed-response.json",
                dict(size=len(exchange.response_payload), error="RESPONSE_LIMIT_EXCEEDED"),
            )
            raise ValueError("Response exceeds designed ceiling")
        (destination / "response.json").write_bytes(exchange.response_payload)
        write_json(destination / "receipt.json", asdict(exchange.receipt))
        raw = await backend.page_evidence(prepared, exchange)
        result["gates"] = verify_page(exchange, raw, backend.welcome.width, backend.welcome.height)
        evidence_snapshot = raw
        gates.advance(Gate.BRIDGE_ALIVE)
        result["readiness"] = [g.name for g in gates.completed]
        result["requests"] = backend.requests
        if (backend.launches, backend.connections, backend.requests) != (1, 1, 1):
            raise ValueError("Exactly one process/connection/application query required")
        if backend.accounting.query_operations != exchange.protocol_operations:
            raise ValueError("Receipt/independent observer accounting mismatch")
        if not 4 <= backend.accounting.query_operations <= 8:
            raise ValueError("Query accounting exhausted")
        verify_freeze(frozen)
    except Exception as error:
        from .terrain_authorization import FailureCode
        from .terrain_failure import failure_diagnostics

        result["diagnostics"] = failure_diagnostics(error, prepared, backend, destination)
        result["error"] = type(error).__name__
        result["failure_code"] = getattr(
            error,
            "code",
            (
                FailureCode.LAUNCH_FAILED
                if backend.launches == 0
                else FailureCode.POSTLAUNCH_PROOF_FAILED
            ),
        ).value
    finally:
        result.update(
            launches=backend.launches, connections=backend.connections, requests=backend.requests
        )
        try:
            cleanup = await backend.cleanup(prepared)
            write_json(destination / "cleanup.raw.json", cleanup)
            # No bind/reconnect/sleep: same Linux structured endpoint verifier.
            if reservation is not None:
                reservation.close()
            endpoints = verify_cleanup_endpoints(prepared, cleanup, reservation)
            write_json(destination / "cleanup.json", dict(cleanup=cleanup, endpoints=endpoints))
            result["gates"]["cleanup"] = True
        except Exception as error:
            result["error"] = result["error"] or type(error).__name__
        for name, path in (
            ("stdout.log", prepared.spec.stdout_path),
            ("stderr.log", prepared.spec.stderr_path),
        ):
            if path.exists():
                with path.open("rb") as stream:
                    raw = stream.read(budget()["capture_bytes"] + 1)
                (destination / name).write_bytes(raw[: budget()["capture_bytes"]])
                if len(raw) > budget()["capture_bytes"]:
                    result["error"] = result["error"] or "CaptureLimitExceeded"
        if evidence_snapshot is not None:
            try:
                from .terrain_logs import log_record

                write_json(
                    destination / "execution-log.json",
                    log_record(
                        evidence_snapshot,
                        (destination / "stderr.log").read_bytes(),
                        prepared.request.request_id,
                    ),
                )
            except Exception as error:
                result["error"] = result["error"] or type(error).__name__
        try:
            prelaunch_record = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
            if native or "canonical_inputs_sha256" in prelaunch_record:
                from .ownership import finalize_cleanup

                finalize_cleanup(prepared, frozen, cleanup)
                write_json(
                    destination / "cleanup-attestation.json",
                    {
                        k: cleanup[k]
                        for k in (
                            "workspace_disposed",
                            "credential_removed",
                            "postrun_integrity_verified",
                        )
                    },
                )
            verify_freeze(frozen)
            if backend.accounting.failed or backend.accounting._counts["cleanup"] != 1:
                raise ValueError("Cleanup/frame accounting invalid")
            result["gates"]["post_run_integrity"] = True
        except Exception as error:
            result["error"] = result["error"] or type(error).__name__
        if "diagnostics" in result:
            result["diagnostics"]["cleanup"] = dict(
                passed=result["gates"].get("cleanup", False),
                reaped=cleanup.get("reaped", False),
                errors=cleanup.get("cleanup_error", []),
            )
        write_json(destination / "accounting.json", backend.accounting.snapshot())
        result["status"] = backend.kind + ("_PASS" if result["error"] is None else "_FAILED")
        write_json(destination / "result.json", result)
        (destination / "artifact-manifest.sha256").write_text(manifest(destination))
    return result


async def authorized_native_run(
    prepared, destination: Path, *, authorize_one_launch=False, authorization=None
):
    """Only a separately sealed operator preparation can reach the native backend."""
    if destination.exists():
        raise ValueError("Attempt already claimed; no retry")
    from .terrain_authorization import LocalOperatorAuthorization

    if (
        not isinstance(authorization, LocalOperatorAuthorization)
        and authorize_one_launch is not True
    ):
        raise PermissionError("Explicit operator authorization required")
    validate_final_prelaunch(prepared, destination, native=True, authorization=authorization)
    from .terrain_native import SinglePageNativeBackend

    return await asyncio.wait_for(
        execute_single_page(
            prepared,
            SinglePageNativeBackend(authorized_one_launch=True),
            destination,
            authorization=authorization,
        ),
        90,
    )


def verify_attempt_inventory(directory: Path, mode: str, *, canonical: bool) -> None:
    """Authorize writer outputs independently of the mutable hash manifest.

    Only successful attempts can reach offline acceptance. Failure diagnostics
    remain retained by the writer, but never belong to an accepted package.
    Canonical objects belong to the separately verified seal, not this root.
    """
    required = {
        "accounting.json",
        "artifact-manifest.sha256",
        "authentication.json",
        "cleanup.json",
        "cleanup.raw.json",
        "execution-log.json",
        "launch-claim.json",
        "receipt.json",
        "response.json",
        "result.json",
        "source-identities.json",
        "stderr.log",
    }
    if canonical:
        required.update(
            {
                "authorization-consumed.json",
                "cleanup-attestation.json",
                "native-launch-claimed.json"
                if mode == "REAL"
                else "controlled-launch-claimed.json",
            }
        )
    # The writer captures stdout only when the owned capture file exists.
    permitted = required | {"stdout.log"}
    actual = {p.name for p in directory.iterdir()}
    if not required <= actual or not actual <= permitted:
        raise ValueError("Retained attempt artifact inventory mismatch")


def verify_cleanup_records(raw: dict, summary: dict, mode: str, accounting: dict) -> None:
    """Reconcile the same post-process observation before disposal attestation."""
    fields = {"reaped", "remaining_processes", "cleanup_error"}
    if mode == "REAL":
        fields |= {
            "pid",
            "graceful_attempted",
            "quit_command",
            "returncode",
            "events",
            "admin_frame_accounting",
        }
    if (
        not isinstance(raw, dict)
        or set(raw) != fields
        or not isinstance(summary, dict)
        or set(summary) != {"cleanup", "endpoints"}
        or not isinstance(summary["cleanup"], dict)
        or summary["cleanup"] != raw
        or raw["reaped"] is not True
        or type(summary["cleanup"].get("reaped")) is not bool
        or raw["remaining_processes"] != []
        or raw["cleanup_error"] != []
    ):
        raise ValueError("Retained cleanup evidence inconsistent or unsuccessful")
    if mode == "REAL" and (
        type(raw["pid"]) is not int
        or raw["pid"] <= 0
        or type(raw["returncode"]) is not int
        or type(raw["graceful_attempted"]) is not bool
        or raw["quit_command"] != "quit"
        or not isinstance(raw["events"], list)
        or not raw["events"]
        or any(not isinstance(event, str) for event in raw["events"])
        or raw["events"][-1] != "reaped"
        or raw["admin_frame_accounting"] != accounting
    ):
        raise ValueError("Retained native cleanup lifecycle mismatch")


def verify_retained_attempt(directory: Path):
    """Read-only offline acceptance. Retained JSON success alone is insufficient."""
    from app.simulation.openttd.tile_facts import TileFactsExchange, TileFactsReceipt

    if not directory.is_absolute() or directory != directory.resolve() or not directory.is_dir():
        raise ValueError("Retained attempt path identity mismatch")
    # Check types before opening anything, including the manifest and result.
    # No directories (hence no nested artifacts) or symlink aliases are outputs.
    for artifact in directory.iterdir():
        if artifact.is_symlink() or not artifact.is_file():
            raise ValueError("Retained attempt artifact is not a regular file")
    if (directory / "artifact-manifest.sha256").read_text() != manifest(directory):
        raise ValueError("Retained artifact integrity mismatch")
    result = json.loads((directory / "result.json").read_text())
    counts = json.loads((directory / "accounting.json").read_text())
    if (
        result["mode"] not in ("REAL", "CONTROLLED")
        or result["status"] != result["mode"] + "_PASS"
        or result["error"] is not None
    ):
        raise ValueError("Failed attempt cannot be accepted")
    if (result["launches"], result["connections"], result["requests"], result["retries"]) != (
        1,
        1,
        1,
        0,
    ):
        raise ValueError("One-shot lifecycle mismatch")
    categories = counts["categories"]
    if counts["query_operations"] != categories["query"]:
        raise ValueError("Receipt/observer query identity mismatch")
    if (
        counts["failed"]
        or categories["establishment"] != 2
        or categories["setup"] != 3
        or categories["cleanup"] != 1
    ):
        raise ValueError("Lifecycle accounting mismatch")
    if (
        not 4 <= categories["query"] <= 8
        or counts["total_post_auth_frames"] != sum(categories.values())
        or counts["total_post_auth_frames"] > 14
    ):
        raise ValueError("Frame ceiling mismatch")
    source = json.loads((directory / "source-identities.json").read_text())
    if not (directory / "execution-log.json").is_file():
        raise ValueError("LEGACY_EVIDENCE_LIMITATION: explicit execution-log scope absent")
    claim = json.loads((directory / "launch-claim.json").read_text())
    if claim["mode"] != result["mode"] or claim["no_retry"] is not True:
        raise ValueError("Launch/result mode or retry policy mismatch")
    seal = Path(claim["prepared_directory"])
    prelaunch = json.loads((seal / "PRELAUNCH.json").read_text())
    verify_attempt_inventory(
        directory, result["mode"], canonical="canonical_inputs_sha256" in prelaunch
    )
    if "canonical_inputs_sha256" in prelaunch:
        from .terrain_retention import verify_inputs

        if (seal / "artifact-manifest.sha256").read_text() != manifest(seal):
            raise ValueError("Retained seal manifest mismatch")
        if (
            (seal / "SEAL.sha256").read_text() != sha256(seal / "PRELAUNCH.json") + "\n"
            or prelaunch["attempt_directory"] != str(directory)
            or source["source_integrity"] != json.loads((seal / "source-freeze.json").read_text())
            or prelaunch["execution_log_policy"] != "terrain-execution-log-v1"
        ):
            raise ValueError("Retained seal/source identity mismatch")
        retained = verify_inputs(seal, prelaunch, source["source_integrity"])
        candidate_record = json.loads(
            retained[str(Path(prelaunch["candidate_path"]) / "CANDIDATE.json")]
        )
        if (
            Path(candidate_record["workspace"]).exists()
            or Path(candidate_record["key_path"]).exists()
        ):
            raise ValueError("Mandatory workspace/credential cleanup incomplete")
        attestation = json.loads((directory / "cleanup-attestation.json").read_text())
        if attestation != dict(
            workspace_disposed=True, credential_removed=True, postrun_integrity_verified=True
        ):
            raise ValueError("Mandatory cleanup attestation absent or invalid")
        if claim["request_sha256"] != prelaunch["request_sha256"]:
            raise ValueError("Launch request identity mismatch")
        if result["mode"] == "REAL":
            verify_retained_authentication(
                json.loads((directory / "authentication.json").read_text()), prelaunch
            )
        consumed_path = directory / "authorization-consumed.json"
        if not consumed_path.is_file():
            raise ValueError("Consumed authorization evidence absent")
        verify_execution_lineage(directory, seal, prelaunch, result["mode"])
    elif result["mode"] == "REAL":
        raise ValueError("LEGACY_EVIDENCE_LIMITATION: durable canonical provenance absent")
    else:
        verify_freeze(source["source_integrity"])
    payload = (directory / "response.json").read_bytes()
    receipt = TileFactsReceipt(**json.loads((directory / "receipt.json").read_text()))
    ex = TileFactsExchange(
        REQUEST.to_bytes(), payload, receipt, protocol_operations=categories["query"]
    )
    from .terrain_logs import verify_log_record

    selected = verify_log_record(
        json.loads((directory / "execution-log.json").read_text()),
        (directory / "stderr.log").read_bytes(),
        REQUEST.request_id,
    )
    verified = verify_page(ex, selected, 64, 64)
    if any(
        type(result["gates"].get(k)) is not type(v) or result["gates"].get(k) != v
        for k, v in verified.items()
    ):
        raise ValueError("Retained semantic acceptance mismatch")
    cleanup = json.loads((directory / "cleanup.json").read_text())
    verify_cleanup_records(
        json.loads((directory / "cleanup.raw.json").read_text()), cleanup, result["mode"], counts
    )
    if (
        cleanup["endpoints"].get("sockets_closed") is not True
        or result["gates"].get("post_run_integrity") is not True
    ):
        raise ValueError("Retained cleanup acceptance mismatch")
    if "canonical_inputs_sha256" in prelaunch:
        from .endpoints import verify_retained_endpoints

        verify_retained_endpoints(cleanup["endpoints"].get("endpoint_verification"), prelaunch)
    # Reconcile the recorded gate only after the cleanup, endpoint and disposal
    # evidence has independently passed. A result flag cannot authorize cleanup.
    if result["gates"].get("cleanup") is not True:
        raise ValueError("Retained result cleanup gate contradicts verified evidence")
    return dict(status="OFFLINE_ACCEPTANCE_PASS", mode=result["mode"], **verified)


def verify_execution_lineage(directory, seal, prelaunch, mode):
    """Structural lineage is universal; controlled grants never prove human consent."""
    import re

    from .terrain_authorization import LOCAL_POLICY, OPERATION, LocalOperatorAuthorization

    consumed_path = directory / "authorization-consumed.json"
    marker_name = (
        "native-launch-claimed.json" if mode == "REAL" else "controlled-launch-claimed.json"
    )
    allowed_authorization = {"authorization-consumed.json"}
    if any(
        p.name.startswith("authorization") and p.name not in allowed_authorization
        for p in directory.iterdir()
    ):
        raise ValueError("Duplicate or conflicting authorization evidence")
    opposite = "controlled-launch-claimed.json" if mode == "REAL" else "native-launch-claimed.json"
    if (directory / opposite).exists():
        raise ValueError("Conflicting invocation mode")
    try:
        if consumed_path.is_symlink() or (directory / marker_name).is_symlink():
            raise ValueError("Aliasing authorization evidence")
        consumed = json.loads(consumed_path.read_bytes())
        marker = json.loads((directory / marker_name).read_bytes())
        fields = set(LocalOperatorAuthorization.__dataclass_fields__) - {"_grant"}
        if set(consumed) != fields | {"state", "no_retry"} or set(marker) != {
            "mode",
            "launch_invocations",
            "no_retry",
            "seal_sha256",
            "attempt_identity",
            "owner_nonce",
            "owner_pid",
            "owner_start",
            "consumed_record_sha256",
        }:
            raise ValueError("Authorization/invocation schema mismatch")
        expected_trust = (
            "LOCAL_OPERATOR_ATTESTED" if mode == "REAL" else "CONTROLLED_OPERATOR_ATTESTED"
        )
        if (
            prelaunch["authorization_policy"] != LOCAL_POLICY
            or consumed["seal_sha256"] != sha256(seal / "PRELAUNCH.json")
            or consumed["attempt_identity"] != prelaunch["attempt_identity"]
            or consumed["attempt_directory"] != str(directory)
            or consumed["trust"] != expected_trust
            or consumed["authorization_mode"] != LOCAL_POLICY
            or consumed["proof_operation"] != OPERATION
            or type(consumed["launch_allowance"]) is not int
            or consumed["launch_allowance"] != 1
            or consumed["no_retry"] is not True
            or consumed["state"] != "STARTED"
            or type(consumed["owner_pid"]) is not int
            or consumed["owner_pid"] <= 0
            or not isinstance(consumed["owner_start"], str)
            or not consumed["owner_start"].isdigit()
            or not isinstance(consumed["owner_nonce"], str)
            or not re.fullmatch(r"[0-9a-f]{32}", consumed["owner_nonce"])
            or marker["mode"] != mode
            or type(marker["launch_invocations"]) is not int
            or marker["launch_invocations"] != 1
            or marker["no_retry"] is not True
            or marker["consumed_record_sha256"] != sha256(consumed_path)
            or any(
                marker[k] != consumed[k]
                for k in (
                    "seal_sha256",
                    "attempt_identity",
                    "owner_nonce",
                    "owner_pid",
                    "owner_start",
                )
            )
        ):
            raise ValueError("Authorization/invocation lineage mismatch")
    except (KeyError, TypeError, OSError) as error:
        raise ValueError("Required authorization/invocation lineage unavailable") from error


def verify_retained_authentication(authentication: dict, prelaunch: dict):
    """Non-secret retained attestation, never a live connection or secret reconstruction."""
    import hashlib

    try:
        auth, welcome = authentication["auth"], authentication["welcome"]
        if (
            auth["encrypted"] is not True
            or auth["state"] != "ACTIVE"
            or auth["method"] != "X25519_AuthorizedKey"
            or auth["public_key"] != prelaunch["public_key"]
            or auth["public_key_sha256"]
            != hashlib.sha256(bytes.fromhex(prelaunch["public_key"])).hexdigest()
            or authentication["protocol"]["version"] != 3
            or welcome["revision"] != "15.3"
            or welcome["dedicated"] is not True
            or (welcome["width"], welcome["height"])
            != (1 << prelaunch["source"]["map_x"], 1 << prelaunch["source"]["map_y"])
            or welcome["seed"] != prelaunch["source"]["seed"]
            or welcome["landscape"] != prelaunch["source"]["landscape"]
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Retained authenticated runtime identity mismatch") from error


def inspect_legacy_attempt(directory: Path):
    """Read-only diagnosis, never certification or fabricated missing scope metadata."""
    import hashlib

    if (directory / "artifact-manifest.sha256").read_text() != manifest(directory):
        raise ValueError("Retained artifact integrity mismatch")
    result = json.loads((directory / "result.json").read_text())
    source = json.loads((directory / "source-identities.json").read_text())
    missing, changed = [], []
    for path, expected in source["source_integrity"].items():
        p = Path(path)
        if not p.is_file():
            missing.append(path)
        elif sha256(p) != expected:
            changed.append(path)
    final = (directory / "stderr.log").read_bytes()
    # Legacy diagnostic reconstruction uses the recorded digest, not a marker
    # search or a known attempt ID. No range inferred here becomes new evidence.
    target = result["gates"].get("evidence_sha256")
    prefix_end = None
    current = hashlib.sha256()
    position = 0
    for line in final.splitlines(keepends=True):
        current.update(line)
        position += len(line)
        if current.hexdigest() == target:
            prefix_end = position
    native = False
    if prefix_end is not None:
        from app.simulation.openttd.tile_facts import TileFactsExchange, TileFactsReceipt

        receipt = TileFactsReceipt(**json.loads((directory / "receipt.json").read_text()))
        exchange = TileFactsExchange(
            REQUEST.to_bytes(), (directory / "response.json").read_bytes(), receipt
        )
        verify_page(exchange, final[:prefix_end], 64, 64)
        native = result["status"] == "REAL_PASS"
    return dict(
        status="AUDIT_BLOCKED",
        recorded_status=result["status"],
        native_single_page_supported=native,
        missing_source_inputs=missing,
        changed_source_inputs=changed,
        legacy_limitations=["EXPLICIT_LOG_SCOPE_ABSENT", "DURABLE_CANONICAL_CONTRACT_ABSENT"],
        diagnostic_prefix_length=prefix_end,
        diagnostic_prefix_sha256=target if prefix_end is not None else None,
        final_log_length=len(final),
        final_log_sha256=hashlib.sha256(final).hexdigest(),
    )
