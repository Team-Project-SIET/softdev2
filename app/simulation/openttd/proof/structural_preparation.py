"""New structural freeze; historical components are support, never query input."""

import hashlib
import json
from pathlib import Path

from .cargo_page_contract import PAGE_BRIDGE_DIGEST
from .enrichment_preparation import checkpoint_head
from .harness import PROJECT, sha256, write_json
from .structural_contract import (
    STRUCTURAL_ATTEMPT_DIRECTORY,
    STRUCTURAL_MODEL,
    STRUCTURAL_REVISION,
    structural_contract,
    structural_contract_digest,
)
from .structural_lineage import capture_lineage


def configuration_identity(directory: Path) -> dict:
    config = json.loads((directory / "sanitized-config.json").read_text())["openttd.cfg"]
    profile = config.split("[game_creation]", 1)[1]
    runtime = json.loads((directory / "runtime-identity.json").read_text())
    graphics = json.loads((directory / "graphics-identity.json").read_text())
    bridge = json.loads((directory / "bridge-package-identity.json").read_text())
    stable = dict(
        generation_profile=profile,
        runtime_sha256=runtime["sha256"],
        graphics_sha256=graphics["archive_sha256"],
        bridge_sha256=bridge["sha256"],
    )
    return dict(
        stable_configuration=stable,
        configuration_digest=hashlib.sha256(
            json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    )


def accounting_identity() -> dict:
    files = {
        name: sha256(PROJECT / name)
        for name in (
            "app/simulation/openttd/secure_admin.py",
            "app/simulation/openttd/admin_session.py",
            "app/simulation/openttd/admin_protocol.py",
            "app/simulation/openttd/proof/structural_contract.py",
            "app/simulation/openttd/proof/structural_native.py",
        )
    }
    return dict(
        files=files,
        sha256=hashlib.sha256(
            json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    )


def check_structural_preparation(directory: Path) -> None:
    """Before credential generation, reject occupied destination or unknown lineage."""
    destination = directory.with_name(STRUCTURAL_ATTEMPT_DIRECTORY)
    if destination.exists():
        raise ValueError("Structural native attempt destination already claimed")
    capture_lineage(directory, STRUCTURAL_REVISION, destination)
    for name in ("cargo_catalog_15_3", "industry_cargo_15_3", "industry_page_bindings_15_3"):
        authority = json.loads((PROJECT / "tests/reference" / name / "manifest.json").read_text())
        for path, entry in authority["files"].items():
            if sha256(PROJECT / path) != entry["sha256"]:
                raise ValueError("Structural native source authority changed")
    from app.simulation.openttd.gamescript_bridge import BRIDGE_DIRECTORY, PACKAGE_FILES

    digest = hashlib.sha256()
    for name in sorted(PACKAGE_FILES):
        raw = (BRIDGE_DIRECTORY / name).read_bytes()
        digest.update(name.encode() + b"\0" + len(raw).to_bytes(8, "big") + raw)
    if digest.hexdigest() != PAGE_BRIDGE_DIGEST:
        raise ValueError("Proven bridge source identity required before credential preparation")
    from .structural_attempt import StructuralProductionRunner
    from .structural_native import StructuralNativeBackend

    if not callable(StructuralProductionRunner) or not callable(StructuralNativeBackend):
        raise ValueError("Structural production integration unavailable")


def freeze_structural_preparation(directory: Path, frozen: dict, bridge_digest: str):
    if bridge_digest != PAGE_BRIDGE_DIGEST:
        raise ValueError("Proven mutation-free cargo bridge identity required")
    write_json(directory / "structural-contract.json", structural_contract())
    write_json(directory / "structural-context.json", configuration_identity(directory))
    write_json(directory / "frame-accounting-identity.json", accounting_identity())
    authorities = {}
    for name in ("cargo_catalog_15_3", "industry_cargo_15_3", "industry_page_bindings_15_3"):
        path = PROJECT / "tests/reference" / name / "manifest.json"
        authority = json.loads(path.read_text())
        for source, entry in authority["files"].items():
            p = PROJECT / source
            if sha256(p) != entry["sha256"]:
                raise ValueError("Structural API authority changed")
            frozen[str(p)] = entry["sha256"]
        frozen[str(path)] = sha256(path)
        authorities[name] = authority
    write_json(directory / "source-authority.json", authorities)
    lineage = capture_lineage(
        directory, STRUCTURAL_REVISION, directory.with_name(STRUCTURAL_ATTEMPT_DIRECTORY)
    )
    write_json(directory / "attempt-lineage.json", lineage)
    history = json.loads((directory / "historical-integrity.json").read_text())
    metadata_path = directory / "PRELAUNCH.json"
    metadata = json.loads(metadata_path.read_text())
    metadata.update(
        state="PREPARED",
        mode="structural-world",
        attempt=1,
        prelaunch_revision=STRUCTURAL_REVISION,
        proof_model=STRUCTURAL_MODEL,
        proof_kind="structural-world",
        attempt_id=lineage["attempt_id"],
        checkpoint_head=checkpoint_head(),
        lineage_digest=lineage["lineage_digest"],
        predecessor_attempt_ids=[r["attempt_id"] for r in lineage["supersedes_prelaunch_attempts"]],
        attempt_directory=str(directory.with_name(STRUCTURAL_ATTEMPT_DIRECTORY)),
        proof_config_sha256=structural_contract_digest(),
        structural_session_config_sha256=structural_contract_digest(),
        frame_accounting_identity=accounting_identity()["sha256"],
        protected_unique_count=history["unique_count"],
        protected_manifest_sha256=history["sha256"],
        semantic_authority=(
            "same-run non-atomic structural observation; no independent semantic sources"
        ),
    )
    metadata["expected_future_evidence"] = [
        "final-report.md",
        "proof-evidence.json",
        "source-freeze.json",
        "source-freeze-post.json",
        "historical-integrity.json",
        "attempt-lineage.json",
        "proof-attempt.json",
        "structural-contract.json",
        "structural-context.json",
        "frame-accounting-identity.json",
        "admin-frame-accounting.json",
        "structural-session.json",
        "structural-observation.json",
        "structural-digest.json",
        "inventory-observation.json",
        "capability-observation.json",
        "catalog-observation.json",
        "transactions.jsonl",
        "process-lifecycle.json",
        "runtime-identity.json",
        "graphics-identity.json",
        "bridge-package-identity.json",
        "sanitized-config.json",
        "admin-auth-evidence.json",
        "protocol-evidence.json",
        "welcome-evidence.json",
        "stdout.log",
        "stderr.log",
        "artifact-manifest.sha256",
    ]
    metadata_path.write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n")
    for path in directory.iterdir():
        if path.is_file() and path.name not in ("source-freeze.json", "artifact-manifest.sha256"):
            frozen[str(path)] = sha256(path)
    (directory / "source-freeze.json").write_text(
        json.dumps(dict(sorted(frozen.items())), sort_keys=True, indent=2) + "\n"
    )
