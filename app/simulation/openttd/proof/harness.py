"""Prelaunch preparation and frozen inputs for one separately authorized ACK attempt."""

import hashlib
import json
import os
import socket
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.simulation.openttd.admin_crypto import AuthorizedKey
from app.simulation.openttd.gamescript_bridge import BRIDGE_DIRECTORY, PACKAGE_FILES, stage_bridge
from app.simulation.openttd.gamescript_protocol import PingRequest
from app.simulation.openttd.runtime.base import LaunchSpecification
from app.simulation.openttd.runtime.config import AdminSettings, RuntimeWorkspace
from app.simulation.openttd.runtime.identity import RuntimeIdentity
from app.simulation.openttd.world_info import WorldInfoRequest

from .causality import PROOF_MODEL
from .graphics import ARCHIVE_SHA256, stage_opengfx

BINARY = Path("/home/fed/Downloads/openttd-15.3-linux-generic-amd64/openttd")
BINARY_SHA256 = "276d5b698a6b706154f3af588f6f885b3aebe518f4ecc8f869abf71383b1904c"
REQUEST = PingRequest("openttd15-real-ack-002")
WORLD_REQUEST = WorldInfoRequest("openttd15-world-info-001")
WORLD_MODEL = "world-info-two-correlated-channels-v1"
PROJECT = Path(__file__).resolve().parents[4]


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value: object) -> None:
    with path.open("x") as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2) + "\n")


def manifest(directory: Path) -> str:
    return "".join(
        f"{sha256(p)}  {p.name}\n"
        for p in sorted(directory.iterdir())
        if p.is_file() and p.name != "artifact-manifest.sha256"
    )


def source_freeze() -> dict[str, str]:
    paths = list((PROJECT / "app/simulation/openttd").rglob("*.py"))
    paths += list(BRIDGE_DIRECTORY.glob("*.nut"))
    paths += [
        PROJECT / "pyproject.toml",
        PROJECT / "uv.lock",
        PROJECT / "app/__init__.py",
        PROJECT / "app/simulation/__init__.py",
        Path(sys.executable).resolve(),
    ]
    if (PROJECT / "CONTEXT.md").is_file():
        paths.append(PROJECT / "CONTEXT.md")
    import monocypher

    paths.append(Path(monocypher.__file__))
    return {str(p.resolve()): sha256(p) for p in sorted(paths)}


def verify_freeze(frozen: dict[str, str]) -> None:
    if any(sha256(Path(path)) != digest for path, digest in frozen.items()):
        raise ValueError("Frozen source/input changed; no launch permitted")


@dataclass
class EndpointReservation:
    game_port: int
    admin_port: int
    sockets: list[socket.socket] = field(repr=False)

    @classmethod
    def allocate(cls, game_port: int = 0, admin_port: int = 0):
        sockets = []
        try:
            game = socket.socket()
            sockets.append(game)
            game.bind(("127.0.0.1", game_port))
            game_port = game.getsockname()[1]
            udp = socket.socket(type=socket.SOCK_DGRAM)
            sockets.append(udp)
            udp.bind(("127.0.0.1", game_port))
            admin = socket.socket()
            sockets.append(admin)
            admin.bind(("127.0.0.1", admin_port))
            admin_port = admin.getsockname()[1]
            if game_port == admin_port:
                raise ValueError("Endpoints must differ")
            return cls(game_port, admin_port, sockets)
        except BaseException:
            for s in sockets:
                s.close()
            raise

    def close(self) -> None:
        for s in self.sockets:
            s.close()
        self.sockets.clear()


@dataclass(frozen=True)
class PreparedProof:
    directory: Path
    spec: LaunchSpecification = field(repr=False)
    key_path: Path = field(repr=False)
    public_key: str
    endpoints: tuple[int, int]
    request: PingRequest | WorldInfoRequest = REQUEST

    def dispose(self) -> None:
        self.key_path.unlink(missing_ok=True)
        self.spec.close()


def launch_argv(binary: Path, config: Path, game_port: int) -> tuple[str, ...]:
    return (
        str(binary),
        f"-D127.0.0.1:{game_port}",
        "-c",
        str(config),
        "-x",
        "-X",
        "-g",
        "-G",
        "42",
        "-dscript=4,grf=1,net=3",
    )


def prepare_proof(
    directory: Path,
    *,
    mode: str = "ack",
    binary: Path = BINARY,
    binary_sha256: str = BINARY_SHA256,
    graphics: Path = PROJECT / "artifacts/runtime/verified-assets/opengfx-8.0-all.zip",
    graphics_sha256: str = ARCHIVE_SHA256,
) -> PreparedProof:
    if mode not in ("ack", "world-info"):
        raise ValueError("Unsupported proof mode")
    request = WORLD_REQUEST if mode == "world-info" else REQUEST
    binary = binary.resolve(strict=True)
    if not binary.is_file() or not os.access(binary, os.X_OK) or sha256(binary) != binary_sha256:
        raise ValueError("Pinned executable verification failed")
    directory = directory.resolve()
    if "openttd-15.3-real-ack-attempt1" in directory.parts or any(
        part.startswith("openttd-15.3-real-ack-attempt1-") for part in directory.parts
    ):
        raise ValueError("Attempt1 history is immutable")
    if any(
        part
        in (
            "openttd-15.3-real-ack-attempt2-prelaunch",
            "openttd-15.3-real-ack-attempt2-prelaunch-gate-failure",
        )
        for part in directory.parts
    ):
        raise ValueError("Previous Attempt2 prelaunch history is immutable")
    for profile in (Path.home() / ".config/openttd", Path.home() / ".local/share/openttd"):
        if directory.is_relative_to(profile.resolve()):
            raise ValueError("Proof preparation must not modify normal profiles")
    directory.mkdir(parents=True, exist_ok=False)
    workspace = RuntimeWorkspace.create(directory / "isolated", retain=True)
    reservation = None
    try:
        reservation = EndpointReservation.allocate()
        key = AuthorizedKey.generate()
        key_path = workspace.root / ".admin-secret"
        # A restricted credential, never part of any evidence/manifest/source hash.
        descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(key._secret)
        workspace.write_config(
            AdminSettings(
                password="",
                port=reservation.admin_port,
                game_port=reservation.game_port,
                authorized_public_key_hex=key.public_hex,
            )
        )
        config = workspace.config.read_text().replace(
            "pause_on_newgame = true", "pause_on_newgame = false"
        )
        config += (
            "\n[game_creation]\nmap_x = 6\nmap_y = 6\nlandscape = temperate\n"
            "starting_year = 1950\nland_generator = 1\ngeneration_seed = 42\n"
            "[difficulty]\nmax_no_competitors = 0\n[misc]\ngraphicsset = OpenGFX\n"
        )
        workspace.config.write_text(config)
        graphics_identity = stage_opengfx(
            graphics, workspace.root / "baseset/OpenGFX", expected_sha256=graphics_sha256
        )
        bridge = stage_bridge(workspace)
        # API and narrow symbols are frozen, and a forbidden API cannot be staged.
        info = (bridge.directory / "info.nut").read_text()
        main = (bridge.directory / "main.nut").read_text()
        forbidden = (
            "GSRoad",
            "GSStation",
            "GSRail",
            "GSBridge",
            "GSTunnel",
            "GSVehicle",
            "GSOrder",
            "GSTile",
            "GSIndustry",
            "GSCompany",
            "RCON",
            "Save(",
            "Load(",
        )
        if 'return "15"' not in info or any(symbol in main for symbol in forbidden):
            raise ValueError("Bridge API/mutation surface changed")
        argv = launch_argv(binary, workspace.config, reservation.game_port)
        identity = RuntimeIdentity(binary, "15.3", binary_sha256)
        spec = LaunchSpecification(
            workspace,
            identity,
            argv,
            workspace.root,
            workspace.environment,
            workspace.logs / "stdout.log",
            workspace.logs / "stderr.log",
        )
        ports = (reservation.game_port, reservation.admin_port)
        from .preflight import historical_snapshot

        write_json(
            directory / "historical-integrity.json",
            historical_snapshot(directory.parent, directory),
        )
        frozen = source_freeze()
        frozen[str(binary)] = binary_sha256
        frozen[str(graphics.resolve())] = graphics_sha256
        for path in workspace.root.rglob("*"):
            if path.is_file() and path != key_path:
                frozen[str(path)] = sha256(path)
        write_json(directory / "source-freeze.json", dict(sorted(frozen.items())))
        write_json(
            directory / "runtime-identity.json",
            {
                **asdict(identity),
                "executable": str(binary),
                "version_authority": "Prior inspection + pinned hash; no inspection/launch here",
            },
        )
        write_json(
            directory / "graphics-identity.json",
            {
                **asdict(graphics_identity),
                "directory": str(graphics_identity.directory),
                "archive_path": str(graphics.resolve()),
            },
        )
        write_json(
            directory / "bridge-package-identity.json",
            {
                "name": "NoMutationBridge",
                "version": 2,
                "api": "15",
                "commands": ["ping", "world_info"],
                "sha256": bridge.sha256,
                "files": {name: sha256(bridge.directory / name) for name in PACKAGE_FILES},
            },
        )
        write_json(
            directory / "sanitized-config.json",
            {
                name: (workspace.root / name).read_text()
                for name in ("openttd.cfg", "private.cfg", "secrets.cfg")
            },
        )
        (directory / "request.json").write_bytes(request.to_bytes())
        write_json(
            directory / "PRELAUNCH.json",
            {
                "state": "PRELAUNCH",
                "expected_future_evidence": [
                    "final-report.md",
                    "proof-evidence.json",
                    "source-freeze.json",
                    "runtime-identity.json",
                    "graphics-identity.json",
                    "bridge-package-identity.json",
                    "sanitized-config.json",
                    "admin-auth-evidence.json",
                    "protocol-evidence.json",
                    "welcome-evidence.json",
                    "request.json",
                    "response.json",
                    "receipt.json",
                    "gamescript-evidence.json",
                    "network-evidence.json",
                    "transaction-correlation.json",
                    "gamescript-observed.log",
                    "process-lifecycle.json",
                    "stdout.log",
                    "stderr.log",
                    "artifact-manifest.sha256",
                ],
                "attempt": 2,
                "prelaunch_revision": 3,
                "proof_model": PROOF_MODEL,
                "gameplay_launches": 0,
                "live_admin_connections": 0,
                "argv": argv,
                "cwd": str(workspace.root),
                "environment": dict(workspace.environment),
                "public_key": key.public_hex,
                "public_key_sha256": key.public_sha256,
                "game_port": ports[0],
                "admin_port": ports[1],
                "request_sha256": hashlib.sha256(request.to_bytes()).hexdigest(),
                "request_size": len(request.to_bytes()),
                "mode": mode,
                "workspace": str(workspace.root),
                "attempt_directory": str(directory.with_name("openttd-15.3-real-ack-attempt2")),
                "note": "Ports re-reserved before launch; not held across sessions.",
            },
        )
        if mode == "world-info":
            metadata_path = directory / "PRELAUNCH.json"
            import json

            metadata = json.loads(metadata_path.read_text())
            metadata.update(
                attempt=1,
                prelaunch_revision=1,
                proof_model=WORLD_MODEL,
                semantic_authority="encrypted SERVER_WELCOME",
                attempt_directory=str(directory.with_name("openttd-15.3-world-info-real-attempt1")),
                expected_future_evidence=[
                    "final-report.md",
                    "proof-evidence.json",
                    "runtime-identity.json",
                    "graphics-identity.json",
                    "bridge-package-identity.json",
                    "source-freeze.json",
                    "sanitized-config.json",
                    "admin-auth-evidence.json",
                    "protocol-evidence.json",
                    "welcome-evidence.json",
                    "world-info-request.json",
                    "world-info-response.json",
                    "transport-receipt.json",
                    "world-info-verification.json",
                    "gamescript-proof-evidence.json",
                    "gamescript-supporting.log",
                    "network-evidence.json",
                    "process-lifecycle.json",
                    "stdout.log",
                    "stderr.log",
                    "artifact-manifest.sha256",
                ],
            )
            metadata_path.write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n")
            write_json(
                directory / "world-info-contract.json",
                {
                    "state": "PRELAUNCH",
                    "protocol": 1,
                    "request_id": request.request_id,
                    "request_type": "world_info",
                    "response_type": "world_info_result",
                    "status": "ok",
                    "response_fields": [
                        "protocol",
                        "request_id",
                        "type",
                        "status",
                        "map_width",
                        "map_height",
                    ],
                    "payload_limit": 512,
                    "request_id_limit": 64,
                    "dimensions": "positive uint16 powers of two",
                    "independent_source": "encrypted SERVER_WELCOME from the same Admin session",
                    "internal_chain": [
                        "BRIDGE_STARTED",
                        "BRIDGE_REQUEST_RECEIVED",
                        "WORLD_INFO_READ",
                        "BRIDGE_RESPONSE_SENT",
                        "BRIDGE_POST_RESPONSE_ALIVE",
                    ],
                    "network_chain": [
                        "WORLD_INFO_REQUEST_SENT",
                        "WORLD_INFO_RESPONSE_RECEIVED",
                        "TRANSPORT_RECEIPT_CREATED",
                        "SEMANTIC_VERIFICATION_CREATED",
                    ],
                    "cross_channel": "semantic correlation only; no wall-clock total order",
                    "world": {"seed": 42, "map_x": 6, "map_y": 6, "landscape": 0},
                    "success": {
                        "launches": 1,
                        "connections": 1,
                        "requests": 1,
                        "retries": 0,
                        "width_match": True,
                        "height_match": True,
                        "mutations": 0,
                        "script_errors": 0,
                        "protocol_errors": 0,
                        "reaped": True,
                        "remaining_processes": 0,
                        "credentials_retained": False,
                        "source_integrity": True,
                        "version": "15.3",
                        "admin_protocol": 3,
                        "secure_authentication": "X25519_AuthorizedKey",
                        "encryption": True,
                        "welcome_valid": True,
                        "subscription": "ADMIN_UPDATE_GAMESCRIPT AUTOMATIC 64",
                        "gamescript_startup": True,
                        "world_info_read": True,
                        "response_send_success": True,
                        "post_response_alive": True,
                        "matching_response_count": 1,
                        "transport_receipt": True,
                        "semantic_verification": "PASS",
                        "raw_supporting_evidence_retained": True,
                    },
                    "failure_policy": (
                        "Prelaunch: zero launch, retain failure, stop. "
                        "Post-launch: retain raw evidence before cleanup, stop/reap; "
                        "no source repair, resend or relaunch. "
                        "Any second run requires fresh explicit authorization."
                    ),
                },
            )
        (directory / "artifact-manifest.sha256").write_text(manifest(directory))
        return PreparedProof(directory, spec, key_path, key.public_hex, ports, request)
    except BaseException as error:
        write_json(
            directory / "PRELAUNCH-FAILURE.json",
            {
                "state": "PRELAUNCH_FAILED",
                "error_type": type(error).__name__,
                "attempt": 2,
                "prelaunch_revision": 3,
                "proof_model": PROOF_MODEL,
                "gameplay_launches": 0,
            },
        )
        workspace.close()
        raise
    finally:
        if reservation:
            reservation.close()
