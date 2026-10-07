"""Future real backend. Instantiation/execution requires separate explicit authorization."""

import asyncio
import json
import os
import subprocess
import time
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import BinaryIO

from app.simulation.openttd.admin_crypto import AuthorizedKey
from app.simulation.openttd.gamescript_protocol import CommunicationReceipt
from app.simulation.openttd.gamescript_transport import GameScriptTransport
from app.simulation.openttd.runtime.base import LaunchSpecification
from app.simulation.openttd.runtime.config import RuntimeWorkspace
from app.simulation.openttd.runtime.identity import RuntimeIdentity
from app.simulation.openttd.secure_admin import AuthDisconnected, AuthState, SecureAdminSession

from .attempt import Gate, Gates
from .cargo_contract import CARGO_MODEL, CARGO_REQUEST
from .cargo_page_contract import PAGE_MODEL, PAGE_REQUEST, PAGE_REVISION
from .catalog_contract import (
    CATALOG_FIRST_REQUEST,
    CATALOG_MODEL,
    CATALOG_REVISION,
)
from .causality import PROOF_MODEL, NetworkProofEvidence
from .enrichment_contract import ENRICHMENT_FIRST_REQUEST, ENRICHMENT_MODEL, ENRICHMENT_REVISION
from .gamescript_evidence import GameScriptProofEvidence, parse_gamescript_evidence
from .graphics import ARCHIVE_SHA256
from .harness import (
    BINARY,
    BINARY_SHA256,
    REQUEST,
    WORLD_MODEL,
    WORLD_REQUEST,
    PreparedProof,
    launch_argv,
    sha256,
)
from .industry_contract import INDUSTRY_ATTEMPT, INDUSTRY_MODEL, INDUSTRY_REQUEST, INDUSTRY_REVISION
from .inventory_contract import INVENTORY_FIRST_REQUEST, INVENTORY_MODEL
from .network_evidence import RecordedProofSession
from .production_contract import (
    PRODUCTION_MODEL,
    PRODUCTION_REQUEST,
    PRODUCTION_REVISION,
)
from .structural_contract import (
    STRUCTURAL_MODEL,
    STRUCTURAL_REVISION,
    structural_first_request,
)


def matching_processes(binary: Path) -> list[int]:
    result = []
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                if (entry / "exe").resolve(strict=True) == binary:
                    result.append(int(entry.name))
            except OSError, RuntimeError:
                pass
    return sorted(result)


def load_prepared(directory: Path, *, mode: str = "ack") -> PreparedProof:
    directory = directory.resolve(strict=True)
    data = json.loads((directory / "PRELAUNCH.json").read_text())
    world = mode == "world-info"
    industry = mode == "industry-page"
    inventory = mode == "industry-inventory"
    cargo = mode == "industry-cargo"
    enrichment = mode == "industry-enrichment"
    page = mode == "cargo-page"
    catalog = mode == "cargo-catalog"
    structural = mode == "structural-world"
    production = mode == "industry-production"
    if mode not in (
        "ack",
        "world-info",
        "industry-page",
        "industry-inventory",
        "industry-cargo",
        "industry-enrichment",
        "cargo-page",
        "cargo-catalog",
        "structural-world",
        "industry-production",
    ):
        raise ValueError("Unsupported proof mode")
    request = {
        "ack": REQUEST,
        "world-info": WORLD_REQUEST,
        "industry-page": INDUSTRY_REQUEST,
        "industry-inventory": INVENTORY_FIRST_REQUEST,
        "industry-cargo": CARGO_REQUEST,
        "industry-enrichment": ENRICHMENT_FIRST_REQUEST,
        "cargo-page": PAGE_REQUEST,
        "cargo-catalog": CATALOG_FIRST_REQUEST,
        "structural-world": structural_first_request(),
        "industry-production": PRODUCTION_REQUEST,
    }[mode]
    if (
        data.get("attempt")
        != (
            json.loads((directory / "attempt-lineage.json").read_text())["attempt_number"]
            if production
            else INDUSTRY_ATTEMPT
            if industry
            else 1
            if world
            or inventory
            or cargo
            or enrichment
            or page
            or catalog
            or structural
            or production
            else 2
        )
        or data.get("prelaunch_revision")
        != (
            PRODUCTION_REVISION
            if production
            else STRUCTURAL_REVISION
            if structural
            else CATALOG_REVISION
            if catalog
            else PAGE_REVISION
            if page
            else ENRICHMENT_REVISION
            if enrichment
            else INDUSTRY_REVISION
            if industry
            else 1
            if world or inventory or cargo
            else 3
        )
        or data.get("proof_model")
        != (
            PRODUCTION_MODEL
            if production
            else STRUCTURAL_MODEL
            if structural
            else CATALOG_MODEL
            if catalog
            else PAGE_MODEL
            if page
            else ENRICHMENT_MODEL
            if enrichment
            else CARGO_MODEL
            if cargo
            else INVENTORY_MODEL
            if inventory
            else INDUSTRY_MODEL
            if industry
            else WORLD_MODEL
            if world
            else PROOF_MODEL
        )
        or (directory / "request.json").read_bytes() != request.to_bytes()
    ):
        raise ValueError("Attempt2 frozen request/preparation required")
    workspace = RuntimeWorkspace.reopen(Path(data["workspace"]))
    if not workspace.root.is_relative_to(directory / "isolated"):
        raise ValueError("Workspace outside preparation")
    identity = RuntimeIdentity(BINARY.resolve(), "15.3", BINARY_SHA256)
    spec = LaunchSpecification(
        workspace,
        identity,
        tuple(data["argv"]),
        workspace.root,
        workspace.environment,
        workspace.logs / "stdout.log",
        workspace.logs / "stderr.log",
    )
    return PreparedProof(
        directory,
        spec,
        workspace.root / ".admin-secret",
        data["public_key"],
        (data["game_port"], data["admin_port"]),
        request,
    )


class NativeBackend:
    kind = "REAL"

    def __init__(self, *, authorized_one_launch: bool = False) -> None:
        if not authorized_one_launch:
            raise PermissionError("Separate one-launch authorization required")
        self.process: subprocess.Popen[bytes] | None = None
        self.session: SecureAdminSession | None = None
        self.transport: GameScriptTransport | None = None
        self._logs: list[BinaryIO] = []
        self._prepared: PreparedProof | None = None
        self._launched = False
        self._sent = False
        self.subscription_evidence: dict = {}
        self._key: AuthorizedKey | None = None
        self.recorded_session: RecordedProofSession | None = None

    @property
    def launches(self) -> int:
        return int(self.process is not None)

    def preflight(self, prepared: PreparedProof) -> None:
        key_path = prepared.key_path
        if (
            key_path.is_symlink()
            or key_path.stat().st_mode & 0o777 != 0o600
            or key_path.stat().st_uid != os.getuid()
        ):
            raise ValueError("Private key permissions invalid")
        self._key = AuthorizedKey.from_bytes(key_path.read_bytes())
        if self._key.public_hex != prepared.public_key:
            raise ValueError("Proof key identity mismatch")
        graphics = json.loads((prepared.directory / "graphics-identity.json").read_text())
        if graphics["archive_sha256"] != ARCHIVE_SHA256:
            raise ValueError("Official graphics identity mismatch")
        if sha256(BINARY) != BINARY_SHA256 or matching_processes(BINARY):
            raise ValueError("Pinned executable/process ownership mismatch")

    def validate_launch(self, prepared: PreparedProof) -> None:
        """Last read-only launch boundary, shared with guarded production preflight."""
        expected = launch_argv(
            BINARY.resolve(), prepared.spec.workspace.config, prepared.endpoints[0]
        )
        if (
            prepared.spec.argv != expected
            or sha256(BINARY) != BINARY_SHA256
            or matching_processes(BINARY)
        ):
            raise ValueError("Native launch identity/ownership mismatch")

    async def launch(self, prepared: PreparedProof) -> None:
        if self._launched:
            raise RuntimeError("No launch retry")
        self.validate_launch(prepared)
        self._prepared = prepared
        self._launched = True
        stdout = prepared.spec.stdout_path.open("xb")
        self._logs.append(stdout)
        stderr = prepared.spec.stderr_path.open("xb")
        self._logs.append(stderr)
        env = os.environ.copy()
        env.update(dict(prepared.spec.environment))
        self.process = subprocess.Popen(
            prepared.spec.argv,
            cwd=prepared.spec.cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
        prepared.spec.lifecycle.process = self.process
        self.health()

    def health(self) -> None:
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError("OpenTTD exited early")
        self._check_logs()

    def _check_logs(self) -> None:
        assert self._prepared is not None
        text = "\n".join(
            p.read_text(errors="replace")
            for p in (self._prepared.spec.stdout_path, self._prepared.spec.stderr_path)
        )
        fatal = (
            "The script died unexpectedly",
            "Error compiling",
            "Fatal error",
            "Script is not started",
            "no longer found",
            "corrupted or missing",
            "but it is incomplete",
            "illegal packet",
            "not supported update frequency",
        )
        if any(marker.lower() in text.lower() for marker in fatal):
            raise RuntimeError("Native script/asset error")

    async def authenticate(self, prepared: PreparedProof, gates: Gates) -> dict:
        key = self._key
        if key is None:
            raise ValueError("Preflight credentials missing")
        deadline = time.monotonic() + 30
        while self.session is None:
            self.health()
            if time.monotonic() >= deadline:
                raise TimeoutError("Admin readiness deadline")
            try:
                self.session = await SecureAdminSession.connect_secure(
                    "127.0.0.1", prepared.endpoints[1], 0.25, key=key
                )
            except AuthDisconnected:
                # A refused TCP connection is a readiness probe, not an auth retry.
                await asyncio.sleep(0.05)
        gates.advance(Gate.ADMIN_CONNECTED)
        await self.session.authenticate("ACK-proof", "1", timeout=10)
        self.health()
        if self.session.state is not AuthState.ACTIVE:
            raise RuntimeError("Secure stream not active")
        protocol = self.session.protocol
        welcome = self.session.welcome
        if protocol is None or welcome is None:
            raise RuntimeError("Handshake incomplete")
        for gate in (Gate.AUTHENTICATED, Gate.ENCRYPTION, Gate.PROTOCOL, Gate.WELCOME):
            gates.advance(gate)
        if (
            protocol.version != 3
            or welcome.revision != "15.3"
            or not welcome.dedicated
            or (welcome.seed, welcome.landscape, welcome.width, welcome.height, welcome.start_day)
            != (42, 0, 64, 64, date(1950, 1, 1).toordinal() + 365)
        ):
            raise ValueError("Unexpected native version/map identity")
        text = prepared.spec.stderr_path.read_text(
            errors="replace"
        ) + prepared.spec.stdout_path.read_text(errors="replace")
        if "Using the OpenGFX base graphics set" not in text:
            raise ValueError("No native OpenGFX load evidence")
        gates.advance(Gate.IDENTITY)
        self.configure_transport(prepared, protocol)
        return {
            "auth": {
                "method": "X25519_AuthorizedKey",
                "public_key": key.public_hex,
                "public_key_sha256": key.public_sha256,
                "encrypted": True,
                "state": self.session.state.name,
            },
            "protocol": asdict(protocol),
            "welcome": asdict(welcome),
        }

    def configure_transport(self, prepared, protocol) -> None:
        if prepared.request != REQUEST:
            raise ValueError("ACK backend requires ping request")
        assert self.session is not None
        self.recorded_session = RecordedProofSession(self.session, REQUEST)
        self.transport = GameScriptTransport(self.recorded_session, protocol)

    async def subscribe(self) -> None:
        assert self.transport is not None
        await self.transport.subscribe(token=0x153, timeout=5)
        self.subscription_evidence = {
            "update_type": 9,
            "frequency": 64,
            "barrier_token": 0x153,
            "confirmation": "encrypted SERVER_PONG",
            "accepted": self.transport.registered,
        }
        self.health()

    async def ping(self, request):
        if self._sent:
            raise RuntimeError("Exactly one proof request allowed")
        assert self.transport is not None
        self._sent = True
        await self.transport.ping(request, timeout=15)
        assert self.transport.response_payload is not None
        return self.transport.response_payload

    async def finish_network(self, receipt: CommunicationReceipt) -> NetworkProofEvidence:
        assert self.recorded_session is not None
        return await self.recorded_session.finish(receipt)

    def network_snapshot(self) -> NetworkProofEvidence | None:
        return None if self.recorded_session is None else self.recorded_session.snapshot()

    async def wait_gamescript(
        self, prepared: PreparedProof, *, complete: bool
    ) -> GameScriptProofEvidence:
        deadline = time.monotonic() + 10
        while True:
            self.health()
            evidence = parse_gamescript_evidence(
                prepared.spec.stderr_path.read_bytes(), prepared.request.request_id
            )
            if evidence.post_ack_alive if complete else evidence.startup_observed:
                if complete:
                    evidence.require_complete()
                return evidence
            if time.monotonic() >= deadline:
                raise TimeoutError("Explicit GameScript evidence deadline")
            # Pace file observations; only a complete native record proves progress.
            await asyncio.sleep(0.01)

    async def cleanup(self, prepared: PreparedProof) -> dict:
        pid = None if self.process is None else self.process.pid
        errors = []
        if self.session is not None:
            try:
                await self.session.close(quit=True)
            except BaseException as error:
                errors.append({"stage": "admin_close", "type": type(error).__name__})
                try:
                    await self.session.close()
                except BaseException as error:
                    errors.append({"stage": "admin_force_close", "type": type(error).__name__})
        graceful = self.process is not None and self.process.poll() is None
        try:
            await asyncio.to_thread(prepared.spec.lifecycle.close)
        except BaseException as error:
            errors.append({"stage": "process_cleanup", "type": type(error).__name__})
        finally:
            for log in self._logs:
                try:
                    log.close()
                except OSError as error:
                    errors.append({"stage": "log_close", "type": type(error).__name__})
            self._logs.clear()
            prepared.key_path.unlink(missing_ok=True)
            self._key = None
        if self._prepared is not None:
            try:
                self._check_logs()
            except RuntimeError as error:
                errors.append({"stage": "final_log_health", "type": type(error).__name__})
        return {
            "pid": pid,
            "graceful_attempted": graceful,
            "quit_command": "quit",
            "returncode": None if self.process is None else self.process.returncode,
            "reaped": self.process is None or self.process.poll() is not None,
            "remaining_processes": matching_processes(BINARY),
            "events": list(prepared.spec.lifecycle.events),
            "cleanup_error": errors,
        }
