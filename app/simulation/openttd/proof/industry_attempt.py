"""Single industry query lifecycle; runtime execution requires separate authorization."""

import json
import shutil
from dataclasses import asdict, dataclass, field
from enum import Enum, auto

from app.simulation.openttd.gamescript_bridge import BridgePackage
from app.simulation.openttd.industry_page import IndustryPageReceipt

from .attempt import Gate, Gates
from .harness import EndpointReservation, manifest, sha256, verify_freeze, write_json
from .industry_contract import (
    INDUSTRY_ATTEMPT_DIRECTORY,
    INDUSTRY_MODEL,
    INDUSTRY_NETWORK_CHAIN,
    INDUSTRY_REQUEST,
)
from .industry_evidence import parse_industry_proof_evidence
from .industry_verification import verify_industry_page
from .preflight import historical_snapshot, preflight_prepared
from .world_attempt import record_prelaunch_failure


class IndustryProofState(Enum):
    PREPARED = auto()
    LAUNCHED = auto()
    ADMIN_ACTIVE = auto()
    INDUSTRY_PAGE_REQUEST_SENT = auto()
    INDUSTRY_PAGE_RESPONSE_RECEIVED = auto()
    TRANSPORT_RECEIPT_CREATED = auto()
    PAGE_VALIDATED = auto()
    POST_RESPONSE_LIVENESS_VERIFIED = auto()
    COMPLETED = auto()
    FAILED = auto()


@dataclass
class IndustryLifecycle:
    states: list[IndustryProofState] = field(default_factory=lambda: [IndustryProofState.PREPARED])

    def advance(self, state: IndustryProofState) -> None:
        if (
            state is not list(IndustryProofState)[len(self.states)]
            or state is IndustryProofState.FAILED
        ):
            raise ValueError("Invalid industry-page proof transition")
        self.states.append(state)

    def fail(self):
        self.states.append(IndustryProofState.FAILED)


def public_verification(verification):
    value = asdict(verification)
    value["runtime_identity"]["executable"] = str(verification.runtime_identity.executable)
    value["bridge_identity"]["directory"] = str(verification.bridge_identity.directory)
    return dict(
        value,
        page_valid=verification.page_valid,
        verified=verification.verified,
        status=verification.status,
    )


def retain_industry_internal(prepared, attempt, response=None):
    path = attempt / "gamescript-supporting.log"
    if not path.exists():
        path.write_bytes(
            prepared.spec.stderr_path.read_bytes() if prepared.spec.stderr_path.exists() else b""
        )
    evidence = parse_industry_proof_evidence(
        path.read_bytes(), INDUSTRY_REQUEST.request_id, source_log=path.name
    )
    if response is not None:
        evidence = evidence.correlate(INDUSTRY_REQUEST, response)
    value = asdict(evidence)
    value["page"].pop("raw_log")
    value["ordered_sequence"] = evidence.ordered_sequence
    if not (attempt / "gamescript-proof-evidence.json").exists():
        write_json(attempt / "gamescript-proof-evidence.json", value)
    return evidence


async def execute_industry_attempt(prepared, backend) -> dict:
    attempt = prepared.directory.with_name(INDUSTRY_ATTEMPT_DIRECTORY)
    if attempt.exists():
        raise ValueError("Industry attempt already claimed; no retry")
    if prepared.directory.with_name(prepared.directory.name + "-gate-failure").exists():
        raise ValueError("Previous industry prelaunch failure; no retry")
    try:
        metadata = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
        if (
            prepared.request != INDUSTRY_REQUEST
            or metadata.get("mode") != "industry-page"
            or metadata.get("proof_model") != INDUSTRY_MODEL
            or metadata.get("attempt_directory") != str(attempt)
        ):
            raise ValueError("Dedicated frozen industry preparation required")
        frozen = json.loads((prepared.directory / "source-freeze.json").read_text())
        secret = prepared.key_path.read_bytes()
        preflight_prepared(prepared, backend)
        reservation = EndpointReservation.allocate(*prepared.endpoints)
    except Exception as error:
        record_prelaunch_failure(prepared.directory, error)
        raise
    lifecycle, gates = IndustryLifecycle(), Gates()
    result = dict(
        mode=backend.kind,
        proof_model=INDUSTRY_MODEL,
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
            "industry-page-contract.json",
        ):
            shutil.copyfile(prepared.directory / name, attempt / name)
        (attempt / "industry-page-request.json").write_bytes(INDUSTRY_REQUEST.to_bytes())
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
        lifecycle.advance(IndustryProofState.LAUNCHED)
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
        lifecycle.advance(IndustryProofState.ADMIN_ACTIVE)
        await backend.subscribe()
        gates.advance(Gate.SUBSCRIPTION)
        startup = await backend.wait_industry(prepared, complete=False)
        if startup.ordered_sequence != ("BRIDGE_STARTED",):
            raise ValueError("Explicit startup required before query")
        gates.advance(Gate.BRIDGE_STARTED)
        backend.health()
        lifecycle.advance(IndustryProofState.INDUSTRY_PAGE_REQUEST_SENT)
        result["requests_sent"] = 1
        exchange = await backend.industry_page(INDUSTRY_REQUEST)
        if exchange.request_payload != INDUSTRY_REQUEST.to_bytes():
            raise ValueError("Industry request differs from frozen request")
        response = exchange.response_payload
        lifecycle.advance(IndustryProofState.INDUSTRY_PAGE_RESPONSE_RECEIVED)
        (attempt / "industry-page-response.json").write_bytes(response)
        receipt = IndustryPageReceipt.correlate(INDUSTRY_REQUEST.to_bytes(), response)
        if receipt != exchange.receipt:
            raise ValueError("Industry receipt mismatch")
        write_json(attempt / "transport-receipt.json", asdict(receipt))
        result.update(receipt=asdict(receipt), transport_verified=True)
        lifecycle.advance(IndustryProofState.TRANSPORT_RECEIPT_CREATED)
        package = json.loads((attempt / "bridge-package-identity.json").read_text())
        bridge = BridgePackage(prepared.spec.workspace.game / "NoMutationBridge", package["sha256"])
        verification = verify_industry_page(
            INDUSTRY_REQUEST,
            response,
            receipt,
            welcome,
            runtime=prepared.spec.identity,
            bridge=bridge,
        )
        result["verification"] = public_verification(verification)
        write_json(attempt / "industry-page-verification.json", result["verification"])
        if not verification.page_valid:
            raise ValueError(verification.status)
        lifecycle.advance(IndustryProofState.PAGE_VALIDATED)
        network = backend.industry_network_evidence()
        if (
            tuple(network.get("ordered_sequence", ())) != INDUSTRY_NETWORK_CHAIN
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
                "Invalid independently ordered/digest-bound Python/Admin industry chain"
            )
        write_json(attempt / "network-evidence.json", network)
        await backend.wait_industry(prepared, complete=True)
        internal = retain_industry_internal(prepared, attempt, response)
        write_json(
            attempt / "transaction-correlation.json",
            dict(
                protocol=1,
                request_id=INDUSTRY_REQUEST.request_id,
                request_type="industry_page",
                response_type="industry_page_result",
                status="ok",
                response_digest=internal.response_digest,
                independent_industry_inventory=None,
            ),
        )
        lifecycle.advance(IndustryProofState.POST_RESPONSE_LIVENESS_VERIFIED)
        gates.advance(Gate.BRIDGE_ALIVE)
        backend.health()
        if not verification.verified:
            raise ValueError(verification.status)
    except BaseException as error:
        result["error"] = str(error)
    finally:
        reservation.close()
        result["launches"] = backend.launches
        try:
            if response is None:
                response = getattr(backend, "industry_response_payload", lambda: None)()
                receipt = getattr(backend, "industry_receipt", lambda: None)()
            if response is not None and not (attempt / "industry-page-response.json").exists():
                (attempt / "industry-page-response.json").write_bytes(response)
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
                    verification = verify_industry_page(
                        INDUSTRY_REQUEST,
                        response,
                        receipt,
                        welcome,
                        runtime=prepared.spec.identity,
                        bridge=BridgePackage(
                            prepared.spec.workspace.game / "NoMutationBridge", package["sha256"]
                        ),
                    )
                    result["verification"] = public_verification(verification)
                    write_json(attempt / "industry-page-verification.json", result["verification"])
                except ValueError as error:
                    result["error"] = result["error"] or str(error)
            if not (attempt / "network-evidence.json").exists():
                write_json(attempt / "network-evidence.json", backend.industry_network_evidence())
            try:
                retain_industry_internal(prepared, attempt, response)
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
            prepared.key_path.unlink(missing_ok=True)
        if getattr(backend, "session", None) is not None:
            result["connections"] = 1
        try:
            endpoints = EndpointReservation.allocate(*prepared.endpoints)
            endpoints.close()
            cleanup["sockets_closed"] = True
        except OSError:
            cleanup["sockets_closed"] = False
            result["error"] = result["error"] or "Runtime endpoints still occupied"
        post = {path: sha256_path_if_present(path) for path in frozen}
        history = json.loads((prepared.directory / "historical-integrity.json").read_text())
        current = historical_snapshot(prepared.directory.parent, prepared.directory)
        integrity = post == frozen and all(
            current.get(name) == files for name, files in history.items()
        )
        if not integrity:
            result["error"] = result["error"] or "Source/historical integrity mismatch"
        for source, name in (
            (prepared.spec.stdout_path, "stdout.log"),
            (prepared.spec.stderr_path, "stderr.log"),
        ):
            if source.exists():
                shutil.copyfile(source, attempt / name)
        if response is not None:
            try:
                parse_industry_proof_evidence(
                    (attempt / "stderr.log").read_bytes(), INDUSTRY_REQUEST.request_id
                ).correlate(INDUSTRY_REQUEST, response)
            except (ValueError, OSError) as error:
                result["error"] = result["error"] or str(error)
        if any(
            secret in path.read_bytes() or secret.hex().encode() in path.read_bytes()
            for path in attempt.iterdir()
            if path.is_file()
        ):
            result["error"] = result["error"] or "Credential redaction failure"
        try:
            from .ownership import finalize_cleanup

            finalize_cleanup(prepared, frozen, cleanup)
            integrity = True
            result["source_integrity"] = True
        except Exception as error:
            integrity = False
            result["source_integrity"] = False
            result["error"] = result["error"] or str(error)
        if result["error"] is None and (
            result["launches"],
            result["connections"],
            result["requests_sent"],
        ) == (1, 1, 1):
            lifecycle.advance(IndustryProofState.COMPLETED)
            result["status"] = backend.kind + "_SUCCESS"
        else:
            lifecycle.fail()
        result.update(states=[state.name for state in lifecycle.states], source_integrity=integrity)
        write_json(attempt / "process-lifecycle.json", cleanup)
        write_json(attempt / "source-freeze-post.json", dict(unchanged=integrity, hashes=post))
        write_json(attempt / "proof-evidence.json", result)
        (attempt / "final-report.md").write_text(
            f"# {result['status']}\n\n"
            "One read-only industry page; no independent industry inventory.\n"
            f"Launches: {result['launches']}; connections: {result['connections']}; "
            f"requests: {result['requests_sent']}; retries: 0.\n"
            f"Transport: {result['transport_verified']}; verification: {result['verification']}; "
            f"error: {result['error']}.\n"
        )
        (attempt / "artifact-manifest.sha256").write_text(manifest(attempt))
    return result


def sha256_path_if_present(path):
    from pathlib import Path

    value = Path(path)
    return sha256(value) if value.is_file() else None
