"""One read-only world-info attempt: independent ordered channels and semantic proof."""

import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum, auto
from pathlib import Path
from typing import Protocol

from app.simulation.openttd.admin_protocol import ServerWelcome
from app.simulation.openttd.gamescript_bridge import BridgePackage
from app.simulation.openttd.world_info import WorldInfoExchange, verify_world_info
from app.simulation.openttd.world_info_evidence import WorldInfoEvidence, parse_world_info_evidence

from .attempt import Gate, Gates
from .harness import (
    WORLD_MODEL,
    WORLD_REQUEST,
    EndpointReservation,
    PreparedProof,
    manifest,
    sha256,
    verify_freeze,
    write_json,
)
from .preflight import historical_snapshot, preflight_prepared

WORLD_NETWORK_CHAIN = (
    "WORLD_INFO_REQUEST_SENT",
    "WORLD_INFO_RESPONSE_RECEIVED",
    "TRANSPORT_RECEIPT_CREATED",
    "SEMANTIC_VERIFICATION_CREATED",
)


@dataclass(frozen=True)
class WorldPythonEvidence:
    ordered_sequence: tuple[str, ...]
    request_sha256: str
    response_sha256: str
    requests_sent: int
    matching_responses: int
    retries: int

    def validate(self, exchange: WorldInfoExchange) -> None:
        exchange.validate()
        if (
            self.ordered_sequence != WORLD_NETWORK_CHAIN
            or (self.requests_sent, self.matching_responses, self.retries) != (1, 1, 0)
            or self.request_sha256 != exchange.receipt.request_payload_sha256
            or self.response_sha256 != exchange.receipt.response_payload_sha256
        ):
            raise ValueError("Invalid independent Python/Admin world-info evidence chain")


class WorldProofState(Enum):
    PREPARED = auto()
    LAUNCHED = auto()
    ADMIN_ACTIVE = auto()
    WORLD_INFO_REQUEST_SENT = auto()
    WORLD_INFO_RESPONSE_RECEIVED = auto()
    SEMANTICALLY_VERIFIED = auto()
    POST_RESPONSE_LIVENESS_VERIFIED = auto()
    COMPLETED = auto()
    FAILED = auto()


@dataclass
class WorldLifecycle:
    states: list[WorldProofState] = field(default_factory=lambda: [WorldProofState.PREPARED])

    def advance(self, state: WorldProofState) -> None:
        if state is not list(WorldProofState)[len(self.states)] or state is WorldProofState.FAILED:
            raise ValueError("Invalid world-info proof transition")
        self.states.append(state)

    def fail(self):
        self.states.append(WorldProofState.FAILED)


class WorldBackend(Protocol):
    kind: str

    @property
    def launches(self) -> int: ...
    @property
    def welcome(self) -> ServerWelcome: ...

    def preflight(self, prepared: PreparedProof) -> None: ...
    async def launch(self, prepared: PreparedProof) -> None: ...
    async def authenticate(self, prepared: PreparedProof, gates: Gates) -> dict: ...
    async def subscribe(self) -> None: ...
    async def world_info(self, request) -> WorldInfoExchange: ...
    async def wait_world(self, prepared: PreparedProof, *, complete: bool) -> WorldInfoEvidence: ...
    def health(self) -> None: ...
    async def cleanup(self, prepared: PreparedProof) -> dict: ...


def retain_internal(prepared, attempt):
    """Copy exact observed records before cleanup, even on malformed/incomplete evidence."""
    path = attempt / "gamescript-supporting.log"
    if not path.exists():
        path.write_bytes(
            prepared.spec.stderr_path.read_bytes() if prepared.spec.stderr_path.exists() else b""
        )
    raw = path.read_bytes()
    evidence = parse_world_info_evidence(raw, prepared.request.request_id, source_log=path.name)
    record_path = attempt / "gamescript-proof-evidence.json"
    if not record_path.exists():
        public = asdict(evidence)
        public.pop("raw_log")
        write_json(record_path, public)
    return evidence


def record_prelaunch_failure(directory: Path, error: Exception) -> None:
    failure = directory.with_name(directory.name + "-gate-failure")
    failure.mkdir(parents=True, exist_ok=False)
    write_json(
        failure / "PRELAUNCH-FAILURE.json",
        {
            "state": "PRELAUNCH_FAILED",
            "attempt_executed": False,
            "error": str(error),
            "launches": 0,
            "connections": 0,
            "requests": 0,
            "retries": 0,
        },
    )
    metadata_path = directory / "PRELAUNCH.json"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text())
        if metadata.get("mode") == "industry-production":
            from .production_lineage import retain_attempt_identity as retain_production_identity

            record = json.loads((failure / "PRELAUNCH-FAILURE.json").read_text())
            record["preparation"] = str(directory)
            (failure / "PRELAUNCH-FAILURE.json").write_text(
                json.dumps(record, sort_keys=True, indent=2) + "\n"
            )
            retain_production_identity(failure, metadata, record)
        if metadata.get("mode") == "structural-world":
            from .structural_lineage import retain_attempt_identity as retain_structural_identity

            record = json.loads((failure / "PRELAUNCH-FAILURE.json").read_text())
            record["preparation"] = str(directory)
            (failure / "PRELAUNCH-FAILURE.json").write_text(
                json.dumps(record, sort_keys=True, indent=2) + "\n"
            )
            retain_structural_identity(failure, metadata, record)
        if metadata.get("mode") == "cargo-catalog":
            from .catalog_lineage import retain_attempt_identity

            record = json.loads((failure / "PRELAUNCH-FAILURE.json").read_text())
            record["preparation"] = str(directory)
            (failure / "PRELAUNCH-FAILURE.json").write_text(
                json.dumps(record, sort_keys=True, indent=2) + "\n"
            )
            retain_attempt_identity(failure, metadata, record)
        if metadata.get("mode") == "cargo-page":
            from .cargo_page_lineage import retain_attempt_identity as retain_page_identity

            record = json.loads((failure / "PRELAUNCH-FAILURE.json").read_text())
            record["preparation"] = str(directory)
            (failure / "PRELAUNCH-FAILURE.json").write_text(
                json.dumps(record, sort_keys=True, indent=2) + "\n"
            )
            retain_page_identity(failure, metadata, record)
        if (
            metadata.get("mode") == "industry-enrichment"
            and metadata.get("prelaunch_revision", 0) >= 4
        ):
            from .enrichment_lineage import retain_attempt_identity

            record = json.loads((failure / "PRELAUNCH-FAILURE.json").read_text())
            record["preparation"] = str(directory)
            (failure / "PRELAUNCH-FAILURE.json").write_text(
                json.dumps(record, sort_keys=True, indent=2) + "\n"
            )
            retain_attempt_identity(failure, metadata, record)
    (failure / "artifact-manifest.sha256").write_text(manifest(failure))


async def execute_world_attempt(prepared: PreparedProof, backend: WorldBackend) -> dict:
    attempt = prepared.directory.with_name("openttd-15.3-world-info-real-attempt1")
    if attempt.exists():
        raise ValueError("World-info attempt already claimed; no retry")
    metadata = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
    if (
        prepared.request != WORLD_REQUEST
        or metadata.get("proof_model") != WORLD_MODEL
        or metadata.get("mode") != "world-info"
        or metadata.get("attempt_directory") != str(attempt)
    ):
        raise ValueError("Dedicated frozen world-info preparation required")
    # All prelaunch gates precede any runtime claim, process or secret cleanup.
    try:
        preflight_prepared(prepared, backend)
        reservation = EndpointReservation.allocate(*prepared.endpoints)
    except Exception as error:
        record_prelaunch_failure(prepared.directory, error)
        raise
    frozen = json.loads((prepared.directory / "source-freeze.json").read_text())
    lifecycle = WorldLifecycle()
    gates = Gates()
    secret = prepared.key_path.read_bytes()
    result = {
        "mode": backend.kind,
        "proof_model": WORLD_MODEL,
        "status": backend.kind + "_FAILED",
        "launches": 0,
        "requests_sent": 0,
        "connections": 0,
        "retries": 0,
        "error": None,
        "receipt": None,
        "verification": None,
    }
    cleanup = {}
    try:
        attempt.mkdir()  # Atomic ownership claim; never write a previously claimed attempt.
    except FileExistsError:
        reservation.close()
        raise ValueError("World-info attempt already claimed; no retry") from None
    exchange = None
    try:
        for name in (
            "source-freeze.json",
            "runtime-identity.json",
            "graphics-identity.json",
            "bridge-package-identity.json",
            "sanitized-config.json",
            "world-info-contract.json",
        ):
            shutil.copyfile(prepared.directory / name, attempt / name)
        (attempt / "world-info-request.json").write_bytes(prepared.request.to_bytes())
        write_json(
            attempt / "launch-claim.json",
            {
                "mode": backend.kind,
                "argv": prepared.spec.argv,
                "workspace": str(prepared.spec.workspace.root),
                "endpoints": prepared.endpoints,
                "no_retry": True,
            },
        )
        reservation.close()
        verify_freeze(frozen)
        await backend.launch(prepared)
        result["launches"] = 1
        write_json(
            attempt / "process-launch.json",
            {
                "pid": getattr(getattr(backend, "process", None), "pid", None),
                "start_observed_utc": datetime.now(UTC).isoformat(),
                "argv": prepared.spec.argv,
                "executable": str(prepared.spec.identity.executable),
                "sha256": prepared.spec.identity.sha256,
                "workspace": str(prepared.spec.workspace.root),
                "game_endpoint": ["127.0.0.1", prepared.endpoints[0]],
                "admin_endpoint": ["127.0.0.1", prepared.endpoints[1]],
            },
        )
        lifecycle.advance(WorldProofState.LAUNCHED)
        gates.advance(Gate.PROCESS)
        auth = await backend.authenticate(prepared, gates)
        result["connections"] = 1
        for name, key in (
            ("admin-auth-evidence.json", "auth"),
            ("protocol-evidence.json", "protocol"),
            ("welcome-evidence.json", "welcome"),
        ):
            write_json(attempt / name, auth[key])
        # Retain the independent source; never derive it from the query result.
        welcome = backend.welcome
        if asdict(welcome) != auth["welcome"]:
            raise ValueError("SERVER_WELCOME evidence/session mismatch")
        lifecycle.advance(WorldProofState.ADMIN_ACTIVE)
        await backend.subscribe()
        gates.advance(Gate.SUBSCRIPTION)
        result["subscription"] = getattr(backend, "subscription_evidence", {})
        startup = await backend.wait_world(prepared, complete=False)
        if startup.ordered_sequence != ("BRIDGE_STARTED",):
            raise ValueError("Explicit GameScript startup missing")
        gates.advance(Gate.BRIDGE_STARTED)
        backend.health()
        lifecycle.advance(WorldProofState.WORLD_INFO_REQUEST_SENT)
        result["requests_sent"] = 1
        exchange = await backend.world_info(prepared.request)
        exchange.validate()
        if exchange.request_payload != prepared.request.to_bytes():
            raise ValueError("World-info request differs from frozen request")
        lifecycle.advance(WorldProofState.WORLD_INFO_RESPONSE_RECEIVED)
        (attempt / "world-info-response.json").write_bytes(exchange.response_payload)
        write_json(attempt / "transport-receipt.json", asdict(exchange.receipt))
        result["receipt"] = asdict(exchange.receipt)
        network = getattr(backend, "world_network_evidence", lambda: {})()
        expected_network = [
            "WORLD_INFO_REQUEST_SENT",
            "WORLD_INFO_RESPONSE_RECEIVED",
            "TRANSPORT_RECEIPT_CREATED",
        ]
        if network and network.get("ordered_sequence") != expected_network:
            raise ValueError("Native network evidence ordering invalid")
        network.update(
            ordered_sequence=[
                "WORLD_INFO_REQUEST_SENT",
                "WORLD_INFO_RESPONSE_RECEIVED",
                "TRANSPORT_RECEIPT_CREATED",
            ],
            request_sha256=exchange.receipt.request_payload_sha256,
            response_sha256=exchange.receipt.response_payload_sha256,
            requests_sent=exchange.requests_sent,
            matching_responses=exchange.matching_responses,
            retries=exchange.retries,
        )
        await backend.wait_world(prepared, complete=True)
        internal = retain_internal(prepared, attempt)
        internal.require_complete(exchange.response)
        package = json.loads((attempt / "bridge-package-identity.json").read_text())
        bridge = BridgePackage(prepared.spec.workspace.game / "NoMutationBridge", package["sha256"])
        verification = verify_world_info(
            exchange,
            internal,
            welcome,
            runtime=prepared.spec.identity,
            bridge=bridge,
            welcome_digest=sha256(attempt / "welcome-evidence.json"),
        )
        public = asdict(verification)
        public["runtime_identity"]["executable"] = str(prepared.spec.identity.executable)
        public["bridge_identity"]["directory"] = str(bridge.directory)
        public.update(
            width_match=verification.width_match,
            height_match=verification.height_match,
            verified=verification.verified,
            source_evidence={
                "welcome": {
                    "file": "welcome-evidence.json",
                    "sha256": sha256(attempt / "welcome-evidence.json"),
                },
                "gamescript": {"file": internal.source_log, "sha256": internal.raw_evidence_digest},
                "response": {
                    "file": "world-info-response.json",
                    "sha256": verification.response_digest,
                },
            },
        )
        write_json(attempt / "world-info-verification.json", public)
        network["ordered_sequence"].append("SEMANTIC_VERIFICATION_CREATED")
        python_evidence = WorldPythonEvidence(
            tuple(network["ordered_sequence"]),
            network["request_sha256"],
            network["response_sha256"],
            network["requests_sent"],
            network["matching_responses"],
            network["retries"],
        )
        python_evidence.validate(exchange)
        write_json(attempt / "network-evidence.json", network)
        result["verification"] = public
        verification.require_match()
        lifecycle.advance(WorldProofState.SEMANTICALLY_VERIFIED)
        # This is a validation state, not a global timestamp ordering of the emitters.
        internal.require_complete(exchange.response)
        lifecycle.advance(WorldProofState.POST_RESPONSE_LIVENESS_VERIFIED)
        gates.advance(Gate.BRIDGE_ALIVE)
        backend.health()
    except BaseException as error:
        result["error"] = str(error)
    finally:
        reservation.close()
        result["launches"] = backend.launches
        if attempt.exists():
            try:
                retain_internal(prepared, attempt)
            except (ValueError, OSError) as error:
                result["error"] = result["error"] or str(error)
                if not (attempt / "gamescript-proof-evidence.json").exists():
                    write_json(
                        attempt / "gamescript-proof-evidence.json",
                        {"valid": False, "error": str(error)},
                    )
        try:
            cleanup = await backend.cleanup(prepared)
            if (
                not cleanup.get("reaped")
                or cleanup.get("remaining_processes")
                or cleanup.get("cleanup_error")
                or not cleanup.get("graceful_attempted")
                or cleanup.get("returncode") != 0
            ):
                raise RuntimeError("Clean shutdown/reap not proven")
        except BaseException as error:
            result["error"] = result["error"] or str(error)
        prepared.key_path.unlink(missing_ok=True)
        if getattr(backend, "session", None) is not None:
            result["connections"] = 1
        try:
            closed_endpoints = EndpointReservation.allocate(*prepared.endpoints)
            closed_endpoints.close()
            cleanup["sockets_closed"] = True
        except OSError:
            cleanup["sockets_closed"] = False
            result["error"] = result["error"] or "Runtime endpoints still occupied"
        post = {path: sha256(Path(path)) if Path(path).is_file() else None for path in frozen}
        history = json.loads((prepared.directory / "historical-integrity.json").read_text())
        current = historical_snapshot(prepared.directory.parent, prepared.directory)
        integrity = post == frozen and all(
            current.get(name) == files for name, files in history.items()
        )
        if not integrity:
            result["error"] = result["error"] or "Source/historical integrity mismatch"
        if attempt.exists():
            for source, name in (
                (prepared.spec.stdout_path, "stdout.log"),
                (prepared.spec.stderr_path, "stderr.log"),
            ):
                if source.exists():
                    shutil.copyfile(source, attempt / name)
            if exchange is not None:
                try:
                    parse_world_info_evidence(
                        prepared.spec.stderr_path.read_bytes(), prepared.request.request_id
                    ).require_complete(exchange.response)
                except (ValueError, OSError) as error:
                    result["error"] = result["error"] or str(error)
            write_json(attempt / "process-lifecycle.json", cleanup)
            write_json(
                attempt / "source-freeze-post.json", {"unchanged": integrity, "hashes": post}
            )
            if any(
                secret in p.read_bytes() or secret.hex().encode() in p.read_bytes()
                for p in attempt.iterdir()
                if p.is_file()
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
            lifecycle.advance(WorldProofState.COMPLETED)
            result["status"] = backend.kind + "_SUCCESS"
        else:
            lifecycle.fail()
        result["states"] = [state.name for state in lifecycle.states]
        result["source_integrity"] = integrity
        if attempt.exists():
            semantic_pass = (
                result["verification"] is not None and result["verification"]["verified"]
            )
            write_json(attempt / "proof-evidence.json", result)
            (attempt / "final-report.md").write_text(
                f"# {result['status']}\n\n"
                "Read-only world-info; two correlated independently ordered evidence channels.\n"
                f"Launches: {result['launches']}; connections: {result['connections']}; "
                f"requests: {result['requests_sent']}; retries: 0.\n"
                f"Semantic verification: {semantic_pass}. "
                f"Error: {result['error']}.\n"
                "Transport receipt and semantic verification are separate. No gameplay mutation.\n"
            )
            (attempt / "artifact-manifest.sha256").write_text(manifest(attempt))
    return result
