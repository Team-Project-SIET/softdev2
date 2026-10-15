"""One owned production transaction, retained failures, no retry or qualification."""

import json
import shutil
from dataclasses import asdict, dataclass, field
from enum import Enum, auto

from app.simulation.openttd.gamescript_bridge import BridgePackage
from app.simulation.openttd.industry_production import PRODUCTION_NETWORK_SEQUENCE
from app.simulation.openttd.industry_production_evidence import parse_industry_production_evidence

from .attempt import Gate, Gates
from .endpoints import verify_cleanup_endpoints
from .harness import EndpointReservation, manifest, verify_freeze, write_json
from .preflight import preflight_prepared
from .production_contract import PRODUCTION_ATTEMPT_DIRECTORY, PRODUCTION_REQUEST
from .production_lineage import retain_attempt_identity
from .production_verification import verify_industry_production
from .world_attempt import record_prelaunch_failure


class ProductionProofState(Enum):
    PREPARED = auto()
    LAUNCHED = auto()
    ADMIN_ACTIVE = auto()
    INDUSTRY_PRODUCTION_REQUEST_SENT = auto()
    INDUSTRY_PRODUCTION_RESPONSE_RECEIVED = auto()
    TRANSPORT_RECEIPT_CREATED = auto()
    PRODUCTION_RECORD_VALIDATED = auto()
    POST_RESPONSE_LIVENESS_VERIFIED = auto()
    RUNTIME_SEMANTICS_VERIFIED = auto()
    CLEANUP_STARTED = auto()
    PROCESS_REAPED = auto()
    ENDPOINTS_CLOSED = auto()
    CREDENTIAL_REMOVED = auto()
    WORKSPACE_DISPOSED = auto()
    POSTRUN_INTEGRITY_VERIFIED = auto()
    COMPLETED = auto()
    FAILED = auto()


@dataclass
class ProductionLifecycle:
    states: list[ProductionProofState] = field(
        default_factory=lambda: [ProductionProofState.PREPARED]
    )

    def advance(self, state):
        if (
            state is ProductionProofState.FAILED
            or state is not list(ProductionProofState)[len(self.states)]
        ):
            raise ValueError("Invalid production proof lifecycle transition")
        self.states.append(state)

    def fail(self):
        self.states.append(ProductionProofState.FAILED)


def public_production_verification(value):
    result = asdict(value)
    result["runtime_identity"]["executable"] = str(value.runtime_identity.executable)
    result["bridge_identity"]["directory"] = str(value.bridge_identity.directory)
    return result


def validate_network(network, receipt):
    if (
        tuple(network.get("ordered_sequence", ())) != PRODUCTION_NETWORK_SEQUENCE
        or (network.get("requests_sent"), network.get("matching_responses"), network.get("retries"))
        != (1, 1, 0)
        or network.get("request_sha256") != receipt.request_payload_sha256
        or network.get("response_sha256") != receipt.response_payload_sha256
    ):
        raise ValueError("Production Python evidence chain/digest mismatch")


async def execute_production_attempt(prepared, backend):
    attempt = prepared.directory.with_name(PRODUCTION_ATTEMPT_DIRECTORY)
    if attempt.exists():
        raise ValueError("Production attempt already claimed; no retry")
    if prepared.directory.with_name(prepared.directory.name + "-gate-failure").exists():
        raise ValueError("Previous production prelaunch failure; no retry")
    try:
        preflight_prepared(prepared, backend)
        metadata = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
        frozen = json.loads((prepared.directory / "source-freeze.json").read_text())
        secret = prepared.key_path.read_bytes()
        reservation = EndpointReservation.allocate(*prepared.endpoints)
    except Exception as error:
        record_prelaunch_failure(prepared.directory, error)
        raise
    try:
        attempt.mkdir()
    except BaseException:
        reservation.close()
        raise
    lifecycle, gates = ProductionLifecycle(), Gates()
    result = dict(
        status=backend.kind + "_FAILED",
        launches=0,
        connections=0,
        requests_sent=0,
        retries=0,
        reconnects=0,
        error=None,
        verification=None,
        receipt=None,
        transport_verified=False,
        qualified_for_planning=False,
        complete_coverage=False,
        independent_production_source=None,
        qualified_real_production_history="NOT YET PROVEN",
        same_run_structural_provenance="NOT PROVEN BY THIS SLICE",
        p08_completion=False,
        proof_kind="industry-production",
        proof_model=metadata["proof_model"],
    )
    exchange = None
    cleanup = {}
    try:
        for source in prepared.directory.iterdir():
            if source.is_file() and source.name != "artifact-manifest.sha256":
                shutil.copyfile(source, attempt / source.name)
        write_json(attempt / "launch-claim.json", dict(argv=prepared.spec.argv, no_retry=True))
        reservation.close()
        verify_freeze(frozen)
        await backend.launch(prepared)
        result["launches"] = 1
        lifecycle.advance(ProductionProofState.LAUNCHED)
        gates.advance(Gate.PROCESS)
        auth = await backend.authenticate(prepared, gates)
        result["connections"] = 1
        for name, key in (
            ("admin-auth-evidence.json", "auth"),
            ("protocol-evidence.json", "protocol"),
            ("welcome-evidence.json", "welcome"),
        ):
            write_json(attempt / name, auth[key])
        if auth["auth"].get("method") != "X25519_AuthorizedKey" or not auth["auth"].get(
            "encrypted"
        ):
            raise ValueError("Secure authorized-key authentication required")
        lifecycle.advance(ProductionProofState.ADMIN_ACTIVE)
        # Startup liveness only; no economy waiting.
        await backend.wait_production(prepared, complete=False)
        await backend.subscribe()
        gates.advance(Gate.SUBSCRIPTION)
        gates.advance(Gate.BRIDGE_STARTED)
        lifecycle.advance(ProductionProofState.INDUSTRY_PRODUCTION_REQUEST_SENT)
        exchange = await backend.industry_production(PRODUCTION_REQUEST)
        if exchange.request_payload != PRODUCTION_REQUEST.to_bytes():
            raise ValueError("Production request differs from immutable freeze")
        exchange.validate()
        result["requests_sent"] = 1
        lifecycle.advance(ProductionProofState.INDUSTRY_PRODUCTION_RESPONSE_RECEIVED)
        (attempt / "production-response.json").write_bytes(exchange.response_payload)
        result.update(receipt=asdict(exchange.receipt), transport_verified=True)
        write_json(attempt / "transport-receipt.json", result["receipt"])
        lifecycle.advance(ProductionProofState.TRANSPORT_RECEIPT_CREATED)
        package = json.loads((attempt / "bridge-package-identity.json").read_text())
        verified = verify_industry_production(
            PRODUCTION_REQUEST,
            exchange.response_payload,
            exchange.receipt,
            runtime=prepared.spec.identity,
            bridge=BridgePackage(
                prepared.spec.workspace.game / "NoMutationBridge", package["sha256"]
            ),
        )
        result["verification"] = public_production_verification(verified)
        write_json(attempt / "production-verification.json", result["verification"])
        if not verified.verified or verified.qualified_for_planning:
            raise ValueError("Single raw record semantic proof failed")
        lifecycle.advance(ProductionProofState.PRODUCTION_RECORD_VALIDATED)
        validate_network(backend.production_network_evidence(), exchange.receipt)
        evidence = await backend.wait_production(prepared, complete=True)
        evidence.require_complete(PRODUCTION_REQUEST, exchange.response)
        lifecycle.advance(ProductionProofState.POST_RESPONSE_LIVENESS_VERIFIED)
        gates.advance(Gate.BRIDGE_ALIVE)
        backend.health()
        lifecycle.advance(ProductionProofState.RUNTIME_SEMANTICS_VERIFIED)
    except BaseException as error:
        result["error"] = str(error)
    finally:
        reservation.close()

        def advance_if_valid(state):
            if result["error"] is None:
                lifecycle.advance(state)

        advance_if_valid(ProductionProofState.CLEANUP_STARTED)
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
            advance_if_valid(ProductionProofState.PROCESS_REAPED)
        except BaseException as error:
            result["error"] = result["error"] or str(error)

        def capture(action, fallback=None):
            try:
                return action()
            except BaseException as error:
                result["error"] = result["error"] or f"Evidence retention failure: {error}"
                return fallback

        response = capture(backend.production_response_payload)
        receipt = capture(backend.production_receipt)
        network = capture(backend.production_network_evidence, {})
        result["launches"] = backend.launches
        result["connections"] = int(backend._connection_claimed)
        result["requests_sent"] = network.get("requests_sent", 0)
        if response is not None and not (attempt / "production-response.json").exists():
            capture(lambda: (attempt / "production-response.json").write_bytes(response))
        if receipt is not None and not (attempt / "transport-receipt.json").exists():
            capture(lambda: write_json(attempt / "transport-receipt.json", asdict(receipt)))
        if result["error"] is None and (
            backend.accounting.total_frames != 10
            or backend.accounting.query_operations != 4
            or backend.accounting.failed
        ):
            result["error"] = "Exact single-request secure frame accounting not proven"
        prepared.key_path.unlink(missing_ok=True)
        try:
            cleanup.update(verify_cleanup_endpoints(prepared, cleanup, reservation))
            cleanup["sockets_closed"] = True
        except OSError as error:
            cleanup["sockets_closed"] = False
            result["error"] = result["error"] or str(error)
        advance_if_valid(ProductionProofState.ENDPOINTS_CLOSED)
        if prepared.key_path.exists():
            result["error"] = result["error"] or "Runtime credential retained"
        advance_if_valid(ProductionProofState.CREDENTIAL_REMOVED)
        for source, name in (
            (prepared.spec.stdout_path, "stdout.log"),
            (prepared.spec.stderr_path, "stderr.log"),
        ):
            if source.exists():
                shutil.copyfile(source, attempt / name)
        raw = prepared.spec.stderr_path.read_bytes() if prepared.spec.stderr_path.exists() else b""
        (attempt / "gamescript-supporting.log").write_bytes(raw)
        try:
            evidence = parse_industry_production_evidence(raw, PRODUCTION_REQUEST.request_id)
            if exchange is None:
                raise ValueError("No semantically admitted production exchange")
            evidence.require_complete(PRODUCTION_REQUEST, exchange.response)
            value = asdict(evidence)
            value.pop("raw_log")
            value["response_digest"] = exchange.receipt.response_payload_sha256
            write_json(attempt / "gamescript-proof-evidence.json", value)
        except Exception as error:
            result["error"] = result["error"] or str(error)
            write_json(
                attempt / "gamescript-proof-evidence.json", dict(valid=False, error=str(error))
            )
        write_json(attempt / "network-evidence.json", network)
        write_json(attempt / "admin-frame-accounting.json", backend.accounting.snapshot())
        if any(
            secret in x.read_bytes() or secret.hex().encode() in x.read_bytes()
            for x in attempt.iterdir()
            if x.is_file()
        ):
            result["error"] = result["error"] or "Credential redaction failure"
        try:
            if not cleanup.get("reaped") or cleanup.get("remaining_processes"):
                raise ValueError("Workspace retained until owned process reaped")
            from .ownership import dispose_and_verify

            # Logs and semantic evidence are now outside the disposable workspace.
            disposal = dispose_and_verify(prepared, frozen)
            advance_if_valid(ProductionProofState.WORKSPACE_DISPOSED)
            result["source_integrity"] = True
            cleanup.update(disposal)
            advance_if_valid(ProductionProofState.POSTRUN_INTEGRITY_VERIFIED)
        except Exception as error:
            result["source_integrity"] = False
            result["error"] = result["error"] or str(error)
        write_json(attempt / "process-lifecycle.json", cleanup)
        if (
            result["error"] is None
            and (result["launches"], result["connections"], result["requests_sent"]) == (1, 1, 1)
            and result["verification"] is not None
        ):
            lifecycle.advance(ProductionProofState.COMPLETED)
            result["status"] = backend.kind + "_SUCCESS"
        else:
            lifecycle.fail()
        result["states"] = [s.name for s in lifecycle.states]
        write_json(attempt / "proof-evidence.json", result)
        (attempt / "final-report.md").write_text(
            f"# {result['status']}\n\nNative binding and raw V1 metrics only.\n"
            "Transported = station-allocation metric; zero/seeded nonzero allowed.\n"
            "Qualified real production history: NOT YET PROVEN.\n"
            "Same-run structural provenance: NOT PROVEN BY THIS SLICE.\n"
            "Independent production source: NONE. Complete coverage: NO. P08 completion: NO.\n"
            f"Error: {result['error']}.\n"
        )
        retain_attempt_identity(attempt, metadata, result)
        (attempt / "artifact-manifest.sha256").write_text(manifest(attempt))
    return result
