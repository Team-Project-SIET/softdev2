"""One-attempt gate/evidence policy. Only an explicit native backend can launch."""

import json
import shutil
from dataclasses import asdict, dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Protocol

from app.simulation.openttd.gamescript_protocol import CommunicationReceipt, PingRequest

from .causality import PROOF_MODEL, NetworkProofEvidence, validate_proof
from .endpoints import verify_cleanup_endpoints
from .gamescript_evidence import GameScriptProofEvidence, parse_gamescript_evidence
from .harness import (
    REQUEST,
    EndpointReservation,
    PreparedProof,
    manifest,
    sha256,
    verify_freeze,
    write_json,
)


class Gate(Enum):
    PROCESS = auto()
    ADMIN_CONNECTED = auto()
    AUTHENTICATED = auto()
    ENCRYPTION = auto()
    PROTOCOL = auto()
    WELCOME = auto()
    IDENTITY = auto()
    SUBSCRIPTION = auto()
    BRIDGE_STARTED = auto()
    BRIDGE_ALIVE = auto()  # Explicit continued-loop marker AND independent network ACK.


@dataclass
class Gates:
    completed: list[Gate] = field(default_factory=list)

    def advance(self, gate: Gate) -> None:
        if len(self.completed) >= len(Gate) or list(Gate)[len(self.completed)] is not gate:
            raise ValueError("Invalid proof readiness transition")
        self.completed.append(gate)


class Backend(Protocol):
    kind: str

    def preflight(self, prepared: PreparedProof) -> None: ...
    async def launch(self, prepared: PreparedProof) -> None: ...
    async def authenticate(self, prepared: PreparedProof, gates: Gates) -> dict[str, Any]: ...
    async def subscribe(self) -> None: ...
    async def ping(self, request: PingRequest) -> bytes: ...
    async def wait_gamescript(
        self, prepared: PreparedProof, *, complete: bool
    ) -> GameScriptProofEvidence: ...
    async def finish_network(self, receipt: CommunicationReceipt) -> NetworkProofEvidence: ...
    def health(self) -> None: ...
    async def cleanup(self, prepared: PreparedProof) -> dict[str, Any]: ...


async def execute_attempt(prepared: PreparedProof, backend: Backend) -> dict[str, Any]:
    """Claims attempt2 once. Never retries a launch, authentication or request.

    Controlled backends produce explicitly CONTROLLED evidence in test directories.
    NativeBackend must only be constructed after separate real-run authorization.
    """
    attempt = prepared.directory.with_name("openttd-15.3-real-ack-attempt2")
    if attempt.exists():
        raise ValueError("Attempt2 already claimed; separate authorization required")
    if prepared.request != REQUEST or "openttd-15.3-real-ack-attempt1" in str(prepared.directory):
        raise ValueError("Attempt1 history/input is immutable; Attempt2 preparation required")
    metadata = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
    if metadata.get("proof_model") != PROOF_MODEL or metadata.get("prelaunch_revision") != 3:
        raise ValueError("Current v3 preparation required; old prelaunch history is immutable")
    if backend.kind == "REAL":
        from .preflight import preflight_prepared

        # Read-only gates fail before runtime claim, cleanup, or history writes.
        preflight_prepared(prepared, backend)
    frozen = {}
    gates = Gates()
    reservation = None
    receipt = None
    network = None
    response = None
    outcome: dict[str, Any] = {
        "mode": backend.kind,
        "proof_model": PROOF_MODEL,
        "status": backend.kind + "_FAILED",
        "receipt": None,
        "launches": 0,
        "requests_sent": 0,
        "automatic_retries": 0,
        "gates": [],
        "error_type": None,
    }
    try:
        if (prepared.directory / "artifact-manifest.sha256").read_text() != manifest(
            prepared.directory
        ):
            raise ValueError("Preparation manifest changed")
        frozen = json.loads((prepared.directory / "source-freeze.json").read_text())
        verify_freeze(frozen)
        from .ownership import validate_ownership

        validate_ownership(prepared, frozen)
        if backend.kind != "REAL":
            backend.preflight(prepared)
        reservation = EndpointReservation.allocate(*prepared.endpoints)
        attempt.mkdir()
        for name in (
            "source-freeze.json",
            "runtime-identity.json",
            "graphics-identity.json",
            "bridge-package-identity.json",
            "sanitized-config.json",
            "request.json",
        ):
            shutil.copyfile(prepared.directory / name, attempt / name)
        write_json(
            attempt / "launch-claim.json",
            {"state": "LAUNCH_CLAIMED", "mode": backend.kind, "no_retry": True},
        )
        reservation.close()
        reservation = None
        await backend.launch(prepared)
        outcome["launches"] = 1
        gates.advance(Gate.PROCESS)
        auth = await backend.authenticate(prepared, gates)
        write_json(attempt / "admin-auth-evidence.json", auth.get("auth", auth))
        write_json(attempt / "protocol-evidence.json", auth.get("protocol", {}))
        write_json(attempt / "welcome-evidence.json", auth.get("welcome", {}))
        await backend.subscribe()
        gates.advance(Gate.SUBSCRIPTION)
        outcome["subscription"] = getattr(backend, "subscription_evidence", {"mode": backend.kind})
        startup = await backend.wait_gamescript(prepared, complete=False)
        if startup.ordered_sequence != ("BRIDGE_STARTED",):
            raise ValueError("Explicit bridge startup missing")
        gates.advance(Gate.BRIDGE_STARTED)
        backend.health()
        outcome["requests_sent"] = 1
        response = await backend.ping(REQUEST)
        (attempt / "request.json").write_bytes(prepared.request.to_bytes())
        (attempt / "response.json").write_bytes(response)
        receipt = CommunicationReceipt.correlate(prepared.request.to_bytes(), response)
        network = await backend.finish_network(receipt)
        network.validate_chain()
        write_json(attempt / "network-evidence.json", network.public_evidence())
        internal = await backend.wait_gamescript(prepared, complete=True)
        internal.require_complete()
        # Snapshot observed bytes and their structure before requesting shutdown.
        observed = prepared.spec.stderr_path.read_bytes()
        internal = parse_gamescript_evidence(
            observed, prepared.request.request_id, source_log="gamescript-observed.log"
        )
        internal.require_complete()
        (attempt / "gamescript-observed.log").write_bytes(observed)
        correlation = validate_proof(internal, network)
        write_json(attempt / "gamescript-evidence.json", asdict(internal))
        write_json(attempt / "transaction-correlation.json", asdict(correlation))
        outcome["transaction_correlation"] = asdict(correlation)
        gates.advance(Gate.BRIDGE_ALIVE)
        backend.health()
    except BaseException as error:
        outcome["error_type"] = type(error).__name__
        outcome["error_reason"] = str(error)
    finally:
        if reservation:
            reservation.close()
        outcome["launches"] = getattr(backend, "launches", outcome["launches"])
        lifecycle = {}
        cleanup_ok = False
        try:
            lifecycle = await backend.cleanup(prepared)
            cleanup_ok = bool(lifecycle.get("reaped")) and not lifecycle.get("remaining_processes")
            if not cleanup_ok or lifecycle.get("cleanup_error"):
                raise RuntimeError("Process/session cleanup incomplete")
            lifecycle.update(verify_cleanup_endpoints(prepared, lifecycle, reservation))
        except BaseException as error:
            outcome["error_type"] = outcome["error_type"] or type(error).__name__
        finally:
            prepared.key_path.unlink(missing_ok=True)
        post = {path: sha256(Path(path)) if Path(path).is_file() else None for path in frozen}
        unchanged = bool(frozen) and post == frozen
        if not unchanged:
            outcome["error_type"] = outcome["error_type"] or "SourceFreezeMismatch"
        if attempt.exists():
            write_json(attempt / "process-lifecycle.json", lifecycle)
            if not (attempt / "network-evidence.json").exists():
                snapshot = getattr(backend, "network_snapshot", lambda: None)()
                if snapshot is not None:
                    write_json(attempt / "network-evidence.json", snapshot.public_evidence())
            if not (attempt / "gamescript-evidence.json").exists():
                raw = (
                    prepared.spec.stderr_path.read_bytes()
                    if prepared.spec.stderr_path.exists()
                    else b""
                )
                try:
                    partial = parse_gamescript_evidence(raw, prepared.request.request_id)
                    write_json(attempt / "gamescript-evidence.json", asdict(partial))
                except ValueError as error:
                    write_json(
                        attempt / "gamescript-evidence.json", {"valid": False, "error": str(error)}
                    )
            for source, name in (
                (prepared.spec.stdout_path, "stdout.log"),
                (prepared.spec.stderr_path, "stderr.log"),
            ):
                if source.exists():
                    shutil.copyfile(source, attempt / name)
            write_json(
                attempt / "source-freeze-post.json", {"unchanged": unchanged, "hashes": post}
            )
        if receipt is not None and outcome["error_type"] is None:
            try:
                final_internal = parse_gamescript_evidence(
                    prepared.spec.stderr_path.read_bytes(), prepared.request.request_id
                )
                final_internal.require_complete()
                if network is None:
                    raise ValueError("Network evidence missing")
                validate_proof(final_internal, network)
            except (ValueError, OSError) as error:
                outcome["error_type"] = type(error).__name__
                outcome["error_reason"] = str(error)
        try:
            from .ownership import finalize_cleanup

            finalize_cleanup(prepared, frozen, lifecycle)
        except Exception as error:
            outcome["error_type"] = outcome["error_type"] or type(error).__name__
            outcome["error_reason"] = outcome.get("error_reason") or str(error)
        if receipt is not None and outcome["error_type"] is None:
            if (
                outcome["launches"] != 1
                or outcome["requests_sent"] != 1
                or not lifecycle.get("graceful_attempted")
                or gates.completed != list(Gate)
            ):
                outcome["error_type"] = "IncompleteProofCriteria"
            else:
                outcome["receipt"] = asdict(receipt)
                outcome["status"] = backend.kind + "_SUCCESS"
                write_json(attempt / "receipt.json", asdict(receipt))
        outcome["gates"] = [g.name for g in gates.completed]
        evidence = attempt if attempt.exists() else prepared.directory
        write_json(
            evidence / ("proof-evidence.json" if attempt.exists() else "PRELAUNCH-FAILURE.json"),
            outcome,
        )
        (evidence / "final-report.md").write_text(
            f"# {outcome['status']}\n\nMode: {backend.kind}. Launches: {outcome['launches']}. "
            f"Requests: {outcome['requests_sent']}. Error type: {outcome['error_type']}.\n"
            "Proof model: two correlated evidence channels, each independently ordered.\n"
            "No total ordering between GameScript ALIVE and Python ACK/receipt.\n"
            "Communication only; no construction/vehicle/order/terrain/finance operation.\n"
        )
        (evidence / "artifact-manifest.sha256").write_text(manifest(evidence))
    return outcome
