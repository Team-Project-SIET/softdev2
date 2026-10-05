"""Read-only production gates shared by the public preflight and native run paths."""

import hashlib
import json
import os
from pathlib import Path

from app.simulation.openttd.admin_crypto import AuthorizedKey
from app.simulation.openttd.gamescript_bridge import PACKAGE_FILES

from .graphics import validate_baseset
from .harness import (
    REQUEST,
    WORLD_REQUEST,
    EndpointReservation,
    PreparedProof,
    launch_argv,
    manifest,
    sha256,
    source_freeze,
    verify_freeze,
)


def historical_snapshot(parent: Path, exclude: Path) -> dict:
    result = {}
    for directory in sorted(parent.iterdir()):
        if not directory.is_dir() or directory == exclude:
            continue
        files = {}
        for path in sorted(directory.rglob("*")):
            if not path.is_file():
                continue
            name = str(path.relative_to(directory))
            if path.name == ".admin-secret":
                # Public identity detects changed secret without retaining its bytes/hash.
                files[name] = {
                    "public_key": AuthorizedKey.from_bytes(path.read_bytes()).public_hex,
                    "mode": path.stat().st_mode & 0o777,
                }
            else:
                files[name] = sha256(path)
        result[directory.name] = files
    return result


def validate_native_inputs(prepared: PreparedProof) -> dict:
    directory = prepared.directory
    if (directory / "artifact-manifest.sha256").read_text() != manifest(directory):
        raise ValueError("Preparation manifest changed")
    frozen = json.loads((directory / "source-freeze.json").read_text())
    verify_freeze(frozen)
    if any(frozen.get(path) != digest for path, digest in source_freeze().items()):
        raise ValueError("Runtime-critical source inventory changed")
    history = json.loads((directory / "historical-integrity.json").read_text())
    current = historical_snapshot(directory.parent, directory)
    if any(current.get(name) != files for name, files in history.items()):
        raise ValueError("Historical artifact integrity changed")
    workspace = prepared.spec.workspace
    if prepared.spec.argv != launch_argv(
        prepared.spec.identity.executable, workspace.config, prepared.endpoints[0]
    ):
        raise ValueError("Launch specification contract changed")
    if prepared.spec.stdout_path.exists() or prepared.spec.stderr_path.exists():
        raise ValueError("Stale native runtime logs")
    graphics = json.loads((directory / "graphics-identity.json").read_text())
    if sha256(Path(graphics["archive_path"])) != graphics["archive_sha256"]:
        raise ValueError("Graphics archive changed")
    if any(
        sha256(Path(graphics["directory"]) / name) != digest for name, digest in graphics["files"]
    ):
        raise ValueError("Extracted graphics changed")
    validate_baseset(Path(graphics["directory"]))
    bridge = json.loads((directory / "bridge-package-identity.json").read_text())
    digest = hashlib.sha256()
    for name in sorted(PACKAGE_FILES):
        content = (workspace.game / "NoMutationBridge" / name).read_bytes()
        digest.update(name.encode() + b"\0" + len(content).to_bytes(8, "big") + content)
    if digest.hexdigest() != bridge["sha256"]:
        raise ValueError("Bridge package digest changed")
    request = prepared.request.to_bytes()
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    if (
        request != (WORLD_REQUEST if metadata.get("mode") == "world-info" else REQUEST).to_bytes()
        or (directory / "request.json").read_bytes() != request
        or hashlib.sha256(request).hexdigest() != metadata["request_sha256"]
    ):
        raise ValueError("Frozen request changed")
    if metadata.get("mode") == "world-info":
        from app.simulation.openttd.world_info_evidence import WORLD_SEQUENCE

        from .world_attempt import WORLD_NETWORK_CHAIN, WorldLifecycle

        contract = json.loads((directory / "world-info-contract.json").read_text())
        if (
            contract["request_id"] != WORLD_REQUEST.request_id
            or tuple(contract["internal_chain"]) != WORLD_SEQUENCE
            or tuple(contract["network_chain"]) != WORLD_NETWORK_CHAIN
            or contract["response_type"] != "world_info_result"
            or metadata["attempt_directory"]
            != str(directory.with_name("openttd-15.3-world-info-real-attempt1"))
        ):
            raise ValueError("World-info evidence contract changed")
        WorldLifecycle()  # Load the same typed partial-order proof model used by the runner.
    if Path(metadata["attempt_directory"]).exists():
        raise ValueError("Proof attempt already claimed")
    config = workspace.config.read_text()
    private = (workspace.root / "private.cfg").read_text()
    secrets = (workspace.root / "secrets.cfg").read_text()
    if (
        "allow_insecure_admin_login = false" not in config
        or "admin_password = \n" not in secrets
        or prepared.public_key not in private
        or "[server_bind_addresses]\n127.0.0.1\n" not in private
    ):
        raise ValueError("Secure loopback-only config required")
    if prepared.key_path.stat().st_mode & 0o777 != 0o600 or not os.access(
        prepared.spec.identity.executable, os.X_OK
    ):
        raise ValueError("Credential/executable permissions invalid")
    key = prepared.key_path.read_bytes()
    if any(
        key in path.read_bytes() or key.hex().encode() in path.read_bytes()
        for path in directory.iterdir()
        if path.is_file()
    ):
        raise ValueError("Private material retained in evidence")
    return {
        "state": "READY_TO_LAUNCH",
        "source_freeze": True,
        "historical_integrity": True,
        "workspace": str(workspace.root),
        "key_path_resolved": True,
        "config": str(workspace.config),
        "graphics": graphics["directory"],
        "bridge": str(workspace.game / "NoMutationBridge"),
        "request_id": prepared.request.request_id,
        "proof_model": metadata["proof_model"],
        "evidence_destination": metadata["attempt_directory"],
        "semantic_contract": metadata.get("semantic_authority"),
        "validator_loaded": True,
        "launches": 0,
        "connections": 0,
        "requests": 0,
    }


def preflight_prepared(prepared: PreparedProof, backend) -> dict:
    result = validate_native_inputs(prepared)
    backend.preflight(prepared)
    reservation = EndpointReservation.allocate(*prepared.endpoints)
    try:
        result["endpoints_reserved"] = [reservation.game_port, reservation.admin_port]
    finally:
        reservation.close()
    return result
