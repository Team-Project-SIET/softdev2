"""Single cargo-page query lifecycle; runtime execution requires separate authorization."""

import json
import shutil
from dataclasses import asdict, dataclass, field
from enum import Enum, auto

from app.simulation.openttd.cargo_page import CargoPageReceipt
from app.simulation.openttd.gamescript_bridge import BridgePackage

from .attempt import Gate, Gates
from .cargo_page_contract import (
    PAGE_ATTEMPT_DIRECTORY,
    PAGE_MODEL,
    PAGE_NETWORK_CHAIN,
    PAGE_REQUEST,
)
from .cargo_page_evidence import parse_page_proof_evidence
from .cargo_page_lineage import retain_attempt_identity
from .cargo_page_verification import verify_cargo_page
from .harness import PROJECT, EndpointReservation, manifest, sha256, verify_freeze, write_json
from .historical_protection import protection_base, validate_protection
from .preflight import preflight_prepared
from .world_attempt import record_prelaunch_failure


class CargoPageProofState(Enum):
    PREPARED = auto()
    LAUNCHED = auto()
    ADMIN_ACTIVE = auto()
    CARGO_PAGE_REQUEST_SENT = auto()
    CARGO_PAGE_RESPONSE_RECEIVED = auto()
    TRANSPORT_RECEIPT_CREATED = auto()
    CARGO_PAGE_VALIDATED = auto()
    POST_RESPONSE_LIVENESS_VERIFIED = auto()
    COMPLETED = auto()
    FAILED = auto()


@dataclass
class CargoPageLifecycle:
    states: list[CargoPageProofState] = field(
        default_factory=lambda: [CargoPageProofState.PREPARED]
    )

    def advance(self, state: CargoPageProofState) -> None:
        if (
            state is not list(CargoPageProofState)[len(self.states)]
            or state is CargoPageProofState.FAILED
        ):
            raise ValueError("Invalid cargo-page proof transition")
        self.states.append(state)

    def fail(self):
        self.states.append(CargoPageProofState.FAILED)


def public_verification(verification):
    value = asdict(verification)
    value["runtime_identity"]["executable"] = str(verification.runtime_identity.executable)
    value["bridge_identity"]["directory"] = str(verification.bridge_identity.directory)
    return dict(
        value,
        verified=verification.verified,
        status=verification.status,
    )


def retain_cargo_internal(prepared, attempt, response=None):
    path = attempt / "gamescript-supporting.log"
    if not path.exists():
        path.write_bytes(
            prepared.spec.stderr_path.read_bytes() if prepared.spec.stderr_path.exists() else b""
        )
    evidence = parse_page_proof_evidence(
        path.read_bytes(), PAGE_REQUEST.request_id, source_log=path.name
    )
    if response is not None:
        evidence = evidence.correlate(PAGE_REQUEST, response)
    value = asdict(evidence)
    value["cargo"].pop("raw_log")
    value["ordered_sequence"] = evidence.ordered_sequence
    if not (attempt / "gamescript-proof-evidence.json").exists():
        write_json(attempt / "gamescript-proof-evidence.json", value)
    return evidence


async def execute_page_attempt(prepared, backend) -> dict:
    attempt = prepared.directory.with_name(PAGE_ATTEMPT_DIRECTORY)
    if attempt.exists():
        raise ValueError("Industry attempt already claimed; no retry")
    if prepared.directory.with_name(prepared.directory.name + "-gate-failure").exists():
        raise ValueError("Previous cargo-page prelaunch failure; no retry")
    try:
        metadata = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
        if (
            prepared.request != PAGE_REQUEST
            or metadata.get("mode") != "cargo-page"
            or metadata.get("proof_model") != PAGE_MODEL
            or metadata.get("attempt_directory") != str(attempt)
        ):
            raise ValueError("Dedicated frozen cargo-page preparation required")
        frozen = json.loads((prepared.directory / "source-freeze.json").read_text())
        secret = prepared.key_path.read_bytes()
        preflight_prepared(prepared, backend)
        reservation = EndpointReservation.allocate(*prepared.endpoints)
    except Exception as error:
        record_prelaunch_failure(prepared.directory, error)
        raise
    lifecycle, gates = CargoPageLifecycle(), Gates()
    result = dict(
        mode=backend.kind,
        proof_model=PAGE_MODEL,
        status=backend.kind + "_FAILED",
        launches=0,
        connections=0,
        requests_sent=0,
        retries=0,
        error=None,
        receipt=None,
        verification=None,
        transport_verified=False,
    )
    try:
        attempt.mkdir()
    except FileExistsError:
        reservation.close()
        raise ValueError("Industry attempt already claimed; no retry") from None
    response = receipt = welcome = None
    cleanup = {}
    try:
        for name in (
            "source-freeze.json",
            "runtime-identity.json",
            "graphics-identity.json",
            "bridge-package-identity.json",
            "sanitized-config.json",
            "source-authority.json",
            "cargo-page-contract.json",
            "world-support.json",
            "historical-integrity.json",
            "attempt-lineage.json",
        ):
            shutil.copyfile(prepared.directory / name, attempt / name)
        (attempt / "cargo-page-request.json").write_bytes(PAGE_REQUEST.to_bytes())
        write_json(
            attempt / "launch-claim.json",
            dict(
                mode=backend.kind,
                argv=prepared.spec.argv,
                endpoints=prepared.endpoints,
                no_retry=True,
            ),
        )
        reservation.close()
        verify_freeze(frozen)
        await backend.launch(prepared)
        result["launches"] = 1
        lifecycle.advance(CargoPageProofState.LAUNCHED)
        gates.advance(Gate.PROCESS)
        auth = await backend.authenticate(prepared, gates)
        result["connections"] = 1
        for name, key in (
            ("admin-auth-evidence.json", "auth"),
            ("protocol-evidence.json", "protocol"),
            ("welcome-evidence.json", "welcome"),
        ):
            write_json(attempt / name, auth[key])
        welcome = backend.welcome
        if asdict(welcome) != auth["welcome"]:
            raise ValueError("Independent SERVER_WELCOME/session mismatch")
        if auth["auth"].get("method") != "X25519_AuthorizedKey" or not auth["auth"].get(
            "encrypted"
        ):
            raise ValueError("Secure authorized-key authentication required")
        if auth["protocol"].get("version") != 3:
            raise ValueError("Admin Protocol 3 required")
        lifecycle.advance(CargoPageProofState.ADMIN_ACTIVE)
        await backend.subscribe()
        gates.advance(Gate.SUBSCRIPTION)
        startup = await backend.wait_cargo(prepared, complete=False)
        if startup.ordered_sequence != ("BRIDGE_STARTED",):
            raise ValueError("Explicit startup required before query")
        gates.advance(Gate.BRIDGE_STARTED)
        backend.health()
        lifecycle.advance(CargoPageProofState.CARGO_PAGE_REQUEST_SENT)
        result["requests_sent"] = 1
        exchange = await backend.cargo_page(PAGE_REQUEST)
        if exchange.request_payload != PAGE_REQUEST.to_bytes():
            raise ValueError("Cargo-page request differs from frozen request")
        response = exchange.response_payload
        lifecycle.advance(CargoPageProofState.CARGO_PAGE_RESPONSE_RECEIVED)
        (attempt / "cargo-page-response.json").write_bytes(response)
        receipt = CargoPageReceipt.correlate_transport(PAGE_REQUEST.to_bytes(), response)
        if receipt != exchange.receipt:
            raise ValueError("Cargo-page receipt mismatch")
        write_json(attempt / "transport-receipt.json", asdict(receipt))
        result.update(receipt=asdict(receipt), transport_verified=True)
        lifecycle.advance(CargoPageProofState.TRANSPORT_RECEIPT_CREATED)
        package = json.loads((attempt / "bridge-package-identity.json").read_text())
        bridge = BridgePackage(prepared.spec.workspace.game / "NoMutationBridge", package["sha256"])
        verification = verify_cargo_page(
            PAGE_REQUEST,
            response,
            receipt,
            runtime=prepared.spec.identity,
            bridge=bridge,
        )
        result["verification"] = public_verification(verification)
        write_json(attempt / "cargo-page-verification.json", result["verification"])
        if not verification.verified:
            raise ValueError(verification.status)
        lifecycle.advance(CargoPageProofState.CARGO_PAGE_VALIDATED)
        network = backend.cargo_network_evidence()
        if (
            tuple(network.get("ordered_sequence", ())) != PAGE_NETWORK_CHAIN
            or (
                network.get("requests_sent"),
                network.get("matching_responses"),
                network.get("retries"),
            )
            != (1, 1, 0)
            or network.get("request_sha256") != receipt.request_payload_sha256
            or network.get("response_sha256") != receipt.response_payload_sha256
        ):
            raise ValueError(
                "Invalid independently ordered/digest-bound Python/Admin cargo-page chain"
            )
        write_json(attempt / "network-evidence.json", network)
        await backend.wait_cargo(prepared, complete=True)
        internal = retain_cargo_internal(prepared, attempt, response)
        write_json(
            attempt / "transaction-correlation.json",
            dict(
                protocol=1,
                request_id=PAGE_REQUEST.request_id,
                request_type="cargo_page",
                response_type="cargo_page_result",
                status="ok",
                response_digest=internal.response_digest,
                independent_second_source_catalog=None,
            ),
        )
        lifecycle.advance(CargoPageProofState.POST_RESPONSE_LIVENESS_VERIFIED)
        gates.advance(Gate.BRIDGE_ALIVE)
        backend.health()
        if not verification.verified:
            raise ValueError(verification.status)
    except BaseException as error:
        result["error"] = str(error)
    finally:
        reservation.close()

        def capture(action):
            try:
                return action()
            except BaseException as error:
                result["error"] = result["error"] or f"Finalization failure: {error}"
                return None

        result["launches"] = backend.launches
        result["reconnects"] = 0
        result["preparation"] = str(prepared.directory)
        result["freeze_revision"] = metadata["prelaunch_revision"]
        result["attempt_id"] = metadata["attempt_id"]
        try:
            if response is None:
                response = getattr(backend, "cargo_response_payload", lambda: None)()
            if receipt is None:
                receipt = getattr(backend, "cargo_receipt", lambda: None)()
            if response is not None and not (attempt / "cargo-page-response.json").exists():
                (attempt / "cargo-page-response.json").write_bytes(response)
            if receipt is not None:
                result.update(receipt=asdict(receipt), transport_verified=True)
                if not (attempt / "transport-receipt.json").exists():
                    write_json(attempt / "transport-receipt.json", asdict(receipt))
            if (
                response is not None
                and receipt is not None
                and welcome is not None
                and result["verification"] is None
            ):
                try:
                    package = json.loads((attempt / "bridge-package-identity.json").read_text())
                    verification = verify_cargo_page(
                        PAGE_REQUEST,
                        response,
                        receipt,
                        runtime=prepared.spec.identity,
                        bridge=BridgePackage(
                            prepared.spec.workspace.game / "NoMutationBridge", package["sha256"]
                        ),
                    )
                    result["verification"] = public_verification(verification)
                    write_json(attempt / "cargo-page-verification.json", result["verification"])
                except ValueError as error:
                    result["error"] = result["error"] or str(error)
                    write_json(
                        attempt / "cargo-page-verification.json",
                        dict(verified=False, error=str(error)),
                    )
            if not (attempt / "network-evidence.json").exists():
                write_json(attempt / "network-evidence.json", backend.cargo_network_evidence())
            try:
                retain_cargo_internal(prepared, attempt, response)
            except (ValueError, OSError) as error:
                result["error"] = result["error"] or str(error)
                if not (attempt / "gamescript-proof-evidence.json").exists():
                    write_json(
                        attempt / "gamescript-proof-evidence.json",
                        dict(valid=False, error=str(error)),
                    )
        except BaseException as error:
            result["error"] = result["error"] or f"Evidence retention failed: {error}"
        finally:
            try:
                cleanup = await backend.cleanup(prepared)
                if (
                    not cleanup.get("reaped")
                    or cleanup.get("remaining_processes")
                    or cleanup.get("cleanup_error")
                    or not cleanup.get("graceful_attempted")
                    or cleanup.get("returncode") != 0
                ):
                    raise ValueError("Clean shutdown/reap not proven")
            except BaseException as error:
                result["error"] = result["error"] or str(error)
            capture(lambda: prepared.key_path.unlink(missing_ok=True))
        if getattr(backend, "session", None) is not None:
            result["connections"] = 1
        # Use observed send accounting, including failures before a frame is sent.
        network = capture(backend.cargo_network_evidence)
        if network is not None:
            result["requests_sent"] = network.get("requests_sent", 0)
        try:
            endpoints = EndpointReservation.allocate(*prepared.endpoints)
            endpoints.close()
            cleanup["sockets_closed"] = True
        except OSError:
            cleanup["sockets_closed"] = False
            result["error"] = result["error"] or "Runtime endpoints still occupied"
        post = capture(lambda: {path: sha256_path_if_present(path) for path in frozen})
        history = capture(
            lambda: json.loads((prepared.directory / "historical-integrity.json").read_text())
        )
        current = capture(
            lambda: validate_protection(
                protection_base(PROJECT, prepared.directory.parent), history
            )
        )
        integrity = (
            post == frozen
            and history is not None
            and current is not None
            and current == history["unique_count"]
        )
        if not integrity:
            result["error"] = result["error"] or "Source/historical integrity mismatch"
        for source, name in (
            (prepared.spec.stdout_path, "stdout.log"),
            (prepared.spec.stderr_path, "stderr.log"),
        ):
            if source.exists():
                capture(lambda source=source, name=name: shutil.copyfile(source, attempt / name))
        if response is not None:
            try:
                parse_page_proof_evidence(
                    (attempt / "stderr.log").read_bytes(), PAGE_REQUEST.request_id
                ).correlate(PAGE_REQUEST, response)
            except (ValueError, OSError) as error:
                result["error"] = result["error"] or str(error)
        leaked = capture(
            lambda: any(
                secret in path.read_bytes() or secret.hex().encode() in path.read_bytes()
                for path in attempt.iterdir()
                if path.is_file()
            )
        )
        if leaked:
            result["error"] = result["error"] or "Credential redaction failure"
        if result["error"] is None and (
            result["launches"],
            result["connections"],
            result["requests_sent"],
        ) == (1, 1, 1):
            lifecycle.advance(CargoPageProofState.COMPLETED)
            result["status"] = backend.kind + "_SUCCESS"
        else:
            lifecycle.fail()
        result.update(states=[state.name for state in lifecycle.states], source_integrity=integrity)
        capture(lambda: write_json(attempt / "process-lifecycle.json", cleanup))
        capture(
            lambda: write_json(
                attempt / "source-freeze-post.json", dict(unchanged=integrity, hashes=post)
            )
        )
        capture(lambda: write_json(attempt / "proof-evidence.json", result))
        capture(
            lambda: (attempt / "final-report.md").write_text(
                f"# {result['status']}\n\n"
                "One read-only native cargo page query; no complete catalog or independent "
                "second-source capability.\n"
                f"Launches: {result['launches']}; connections: {result['connections']}; "
                f"requests: {result['requests_sent']}; retries: 0.\n"
                f"Transport: {result['transport_verified']}; "
                f"verification: {result['verification']}; "
                f"error: {result['error']}.\n"
            )
        )
        capture(lambda: (attempt / "artifact-manifest.sha256").write_text(manifest(attempt)))
        if cleanup.get("reaped") and not cleanup.get("remaining_processes"):
            capture(prepared.dispose)
        # A final artifact/disposal error must never leave a success classification.
        if result["error"] is not None and result["status"] == backend.kind + "_SUCCESS":
            result["status"] = backend.kind + "_FAILED"
            lifecycle.fail()
            result["states"] = [state.name for state in lifecycle.states]
            capture(
                lambda: (attempt / "proof-evidence.json").write_text(
                    json.dumps(result, sort_keys=True, indent=2) + "\n"
                )
            )
            capture(
                lambda: (attempt / "final-report.md").write_text(
                    f"# {result['status']}\n\nFinalization failure: {result['error']}.\n"
                )
            )
            capture(lambda: (attempt / "artifact-manifest.sha256").write_text(manifest(attempt)))
    retain_attempt_identity(attempt, metadata, result)
    (attempt / "artifact-manifest.sha256").write_text(manifest(attempt))
    return result


def sha256_path_if_present(path):
    from pathlib import Path

    value = Path(path)
    return sha256(value) if value.is_file() else None
