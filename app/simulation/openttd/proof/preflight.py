"""Read-only production gates shared by the public preflight and native run paths."""

import hashlib
import json
import os
from pathlib import Path

from app.simulation.openttd.admin_crypto import AuthorizedKey
from app.simulation.openttd.gamescript_bridge import PACKAGE_FILES

from .cargo_contract import (
    CARGO_ATTEMPT_DIRECTORY,
    CARGO_BRIDGE_DIGEST,
    CARGO_REQUEST,
    cargo_contract,
    cargo_contract_digest,
)
from .cargo_page_contract import (
    PAGE_ATTEMPT_DIRECTORY,
    PAGE_BRIDGE_DIGEST,
    PAGE_REQUEST,
    PAGE_REVISION,
    page_contract,
    page_contract_digest,
)
from .catalog_contract import (
    CATALOG_ATTEMPT_DIRECTORY,
    CATALOG_FIRST_REQUEST,
    CATALOG_REVISION,
)
from .enrichment_contract import (
    ENRICHMENT_ATTEMPT_DIRECTORY,
    ENRICHMENT_FIRST_REQUEST,
    enrichment_contract,
    enrichment_contract_digest,
)
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
from .industry_contract import INDUSTRY_ATTEMPT_DIRECTORY, INDUSTRY_REQUEST, industry_contract
from .inventory_contract import (
    INVENTORY_ATTEMPT_DIRECTORY,
    INVENTORY_FIRST_REQUEST,
    inventory_contract,
    inventory_contract_digest,
)
from .structural_contract import (
    STRUCTURAL_ATTEMPT_DIRECTORY,
    STRUCTURAL_REVISION,
    structural_first_request,
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
    metadata = json.loads((directory / "PRELAUNCH.json").read_text())
    protected_count = None
    lineage_count = None
    if metadata.get("mode") in (
        "industry-enrichment",
        "cargo-page",
        "cargo-catalog",
        "structural-world",
    ):
        from .harness import PROJECT
        from .historical_protection import protection_base, validate_protection

        protected_count = validate_protection(protection_base(PROJECT, directory.parent), history)
        if (
            metadata.get("protected_unique_count") != protected_count
            or metadata.get("protected_manifest_sha256") != history["sha256"]
        ):
            raise ValueError("Historical frozen manifest identity mismatch")
    else:
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
        request
        != {
            "world-info": WORLD_REQUEST,
            "industry-page": INDUSTRY_REQUEST,
            "industry-inventory": INVENTORY_FIRST_REQUEST,
            "industry-cargo": CARGO_REQUEST,
            "industry-enrichment": ENRICHMENT_FIRST_REQUEST,
            "cargo-page": PAGE_REQUEST,
            "cargo-catalog": CATALOG_FIRST_REQUEST,
            "structural-world": structural_first_request(),
        }.get(metadata.get("mode"), REQUEST).to_bytes()
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
    if metadata.get("mode") == "industry-page":
        if directory.with_name(directory.name + "-gate-failure").exists():
            raise ValueError("Previous industry prelaunch failure; no retry")
        from .industry_attempt import IndustryLifecycle
        from .industry_verification import verify_industry_page

        contract = json.loads((directory / "industry-page-contract.json").read_text())
        if contract != industry_contract() or metadata["attempt_directory"] != str(
            directory.with_name(INDUSTRY_ATTEMPT_DIRECTORY)
        ):
            raise ValueError("Industry-page evidence contract changed")
        if bridge["commands"] != ["ping", "world_info", "industry_page"] or bridge["api"] != "15":
            raise ValueError("Industry bridge command/API identity changed")
        IndustryLifecycle()
        if not callable(verify_industry_page):
            raise ValueError("Industry validator unavailable")
    if metadata.get("mode") == "industry-inventory":
        from .inventory_attempt import InventoryLifecycle
        from .inventory_contract import verify_inventory

        if directory.with_name(directory.name + "-gate-failure").exists():
            raise ValueError("Previous inventory prelaunch failure; no retry")
        contract = json.loads((directory / "inventory-contract.json").read_text())
        if (
            contract != inventory_contract()
            or metadata.get("proof_config_sha256") != inventory_contract_digest()
            or metadata["attempt_directory"]
            != str(directory.with_name(INVENTORY_ATTEMPT_DIRECTORY))
        ):
            raise ValueError("Inventory frozen evidence/session contract changed")
        if bridge["sha256"] != contract["bridge_digest"] or not callable(verify_inventory):
            raise ValueError("Inventory bridge/validator changed")
        InventoryLifecycle()
    if metadata.get("mode") == "industry-cargo":
        from .cargo_attempt import CargoLifecycle
        from .cargo_verification import verify_industry_cargo

        if directory.with_name(directory.name + "-gate-failure").exists():
            raise ValueError("Previous cargo prelaunch failure; no retry")
        contract = json.loads((directory / "industry-cargo-contract.json").read_text())
        if (
            contract != cargo_contract()
            or metadata.get("proof_config_sha256") != cargo_contract_digest()
            or metadata["attempt_directory"] != str(directory.with_name(CARGO_ATTEMPT_DIRECTORY))
            or bridge["sha256"] != CARGO_BRIDGE_DIGEST
            or bridge["commands"] != ["ping", "world_info", "industry_page", "industry_cargo"]
            or bridge["api"] != "15"
        ):
            raise ValueError("Cargo frozen evidence/bridge contract changed")
        authority = json.loads((directory / "source-authority.json").read_text())
        if authority.get("version") != "OpenTTD 15.3" or not any(
            "script_cargolist.hpp" in p for p in authority.get("files", {})
        ):
            raise ValueError("Cargo native API authority unavailable")
        CargoLifecycle()
        if not callable(verify_industry_cargo):
            raise ValueError("Cargo validator unavailable")
    if metadata.get("mode") == "industry-enrichment":
        from app.simulation.openttd.industry_enrichment import IndustryEnrichmentSession

        from .enrichment_attempt import EnrichmentLifecycle
        from .enrichment_contract import ENRICHMENT_REVISION
        from .enrichment_lineage import validate_lineage
        from .enrichment_preparation import checkpoint_head

        lineage = json.loads((directory / "attempt-lineage.json").read_text())
        lineage_count = validate_lineage(
            directory,
            lineage,
            ENRICHMENT_REVISION,
            directory.with_name(ENRICHMENT_ATTEMPT_DIRECTORY),
        )
        if (
            metadata.get("lineage_digest") != lineage["lineage_digest"]
            or metadata.get("attempt_id") != lineage["attempt_id"]
            or metadata.get("predecessor_attempt_ids")
            != [row["attempt_id"] for row in lineage["supersedes_prelaunch_attempts"]]
        ):
            raise ValueError("Frozen attempt lineage metadata mismatch")
        contract = json.loads((directory / "enrichment-contract.json").read_text())
        if (
            contract != enrichment_contract()
            or metadata.get("proof_config_sha256") != enrichment_contract_digest()
            or metadata["attempt_directory"]
            != str(directory.with_name(ENRICHMENT_ATTEMPT_DIRECTORY))
            or metadata.get("checkpoint_head") != checkpoint_head()
            or bridge["sha256"] != CARGO_BRIDGE_DIGEST
            or bridge["commands"] != ["ping", "world_info", "industry_page", "industry_cargo"]
        ):
            raise ValueError("Enrichment frozen contract/checkpoint/bridge changed")
        EnrichmentLifecycle()
        if not callable(IndustryEnrichmentSession):
            raise ValueError("Enrichment session unavailable")
    if metadata.get("mode") == "cargo-page":
        from .cargo_page_attempt import CargoPageLifecycle
        from .cargo_page_lineage import validate_lineage
        from .cargo_page_verification import verify_cargo_page
        from .enrichment_preparation import checkpoint_head

        lineage = json.loads((directory / "attempt-lineage.json").read_text())
        lineage_count = validate_lineage(
            directory, lineage, PAGE_REVISION, directory.with_name(PAGE_ATTEMPT_DIRECTORY)
        )
        authority = json.loads((directory / "source-authority.json").read_text())
        if (
            json.loads((directory / "cargo-page-contract.json").read_text()) != page_contract()
            or metadata.get("proof_config_sha256") != page_contract_digest()
            or metadata.get("attempt_directory") != str(directory.with_name(PAGE_ATTEMPT_DIRECTORY))
            or metadata.get("proof_kind") != "cargo-page"
            or metadata.get("attempt_id") != lineage["attempt_id"]
            or metadata.get("lineage_digest") != lineage["lineage_digest"]
            or metadata.get("predecessor_attempt_ids")
            != [r["attempt_id"] for r in lineage["supersedes_prelaunch_attempts"]]
            or metadata.get("checkpoint_head") != checkpoint_head()
            or bridge["sha256"] != PAGE_BRIDGE_DIGEST
            or bridge["commands"] != page_contract()["commands"]
            or authority.get("version") != "15.3"
            or not any("script_cargo.cpp" in name for name in authority.get("files", {}))
        ):
            raise ValueError(
                "Cargo-page frozen kind/request/destination/API/contract identity mismatch"
            )
        CargoPageLifecycle()
        if not callable(verify_cargo_page):
            raise ValueError("Cargo-page validator unavailable")
    if metadata.get("mode") == "cargo-catalog":
        from app.simulation.openttd.cargo_catalog import CargoCatalogSession

        from .catalog_attempt import CatalogLifecycle
        from .catalog_contract import catalog_contract, catalog_contract_digest
        from .catalog_lineage import validate_lineage
        from .enrichment_preparation import checkpoint_head

        lineage = json.loads((directory / "attempt-lineage.json").read_text())
        lineage_count = validate_lineage(
            directory, lineage, CATALOG_REVISION, directory.with_name(CATALOG_ATTEMPT_DIRECTORY)
        )
        authority = json.loads((directory / "source-authority.json").read_text())
        if (
            json.loads((directory / "catalog-contract.json").read_text()) != catalog_contract()
            or metadata.get("proof_config_sha256") != catalog_contract_digest()
            or metadata.get("attempt_directory")
            != str(directory.with_name(CATALOG_ATTEMPT_DIRECTORY))
            or metadata.get("proof_kind") != "cargo-catalog"
            or metadata.get("attempt_id") != lineage["attempt_id"]
            or metadata.get("lineage_digest") != lineage["lineage_digest"]
            or metadata.get("predecessor_attempt_ids")
            != [e["attempt_id"] for e in lineage["supersedes_prelaunch_attempts"]]
            or metadata.get("checkpoint_head") != checkpoint_head()
            or bridge["sha256"] != PAGE_BRIDGE_DIGEST
            or authority.get("version") != "15.3"
        ):
            raise ValueError("Catalog frozen kind/config/destination/API/lineage mismatch")
        CatalogLifecycle()
        if not callable(CargoCatalogSession):
            raise ValueError("Catalog assembly unavailable")
    if metadata.get("mode") == "structural-world":
        from .enrichment_preparation import checkpoint_head
        from .structural_contract import structural_contract, structural_contract_digest
        from .structural_lineage import validate_lineage
        from .structural_preparation import accounting_identity, configuration_identity

        lineage = json.loads((directory / "attempt-lineage.json").read_text())
        lineage_count = validate_lineage(
            directory,
            lineage,
            STRUCTURAL_REVISION,
            directory.with_name(STRUCTURAL_ATTEMPT_DIRECTORY),
        )
        if (
            json.loads((directory / "structural-contract.json").read_text())
            != structural_contract()
            or json.loads((directory / "structural-context.json").read_text())
            != configuration_identity(directory)
            or json.loads((directory / "frame-accounting-identity.json").read_text())
            != accounting_identity()
            or metadata.get("proof_config_sha256") != structural_contract_digest()
            or metadata.get("structural_session_config_sha256") != structural_contract_digest()
            or metadata.get("frame_accounting_identity") != accounting_identity()["sha256"]
            or metadata.get("attempt_directory")
            != str(directory.with_name(STRUCTURAL_ATTEMPT_DIRECTORY))
            or metadata.get("proof_kind") != "structural-world"
            or metadata.get("checkpoint_head") != checkpoint_head()
            or metadata.get("attempt_id") != lineage["attempt_id"]
            or metadata.get("lineage_digest") != lineage["lineage_digest"]
            or metadata.get("predecessor_attempt_ids")
            != [r["attempt_id"] for r in lineage["supersedes_prelaunch_attempts"]]
            or bridge["sha256"] != PAGE_BRIDGE_DIGEST
        ):
            raise ValueError(
                "Structural frozen accounting/kind/config/destination/lineage mismatch"
            )
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
    if AuthorizedKey.from_bytes(key).public_hex != prepared.public_key:
        raise ValueError("Private/public authorized key mismatch")
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
        "lineage_validated": lineage_count is not None,
        "lineage_predecessor_count": lineage_count,
        "protected_unique_count": protected_count,
        "protected_manifest_sha256": history.get("sha256"),
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
        "welcome_bounds_validator_wired": metadata.get("mode")
        in ("industry-page", "industry-inventory", "industry-enrichment"),
        "canonical_evidence_policy_loaded": metadata.get("mode")
        in (
            "industry-page",
            "industry-inventory",
            "industry-cargo",
            "industry-enrichment",
            "cargo-page",
            "cargo-catalog",
            "structural-world",
        ),
        "enrichment_contract": enrichment_contract()
        if metadata.get("mode") == "industry-enrichment"
        else None,
        "inventory_phase_loaded": metadata.get("mode") == "industry-enrichment",
        "capability_phase_loaded": metadata.get("mode") == "industry-enrichment",
        "same_run_digest_wiring_loaded": metadata.get("mode") == "industry-enrichment",
        "native_api_authority_loaded": metadata.get("mode")
        in ("industry-cargo", "cargo-page", "cargo-catalog"),
        "catalog_session_loaded": metadata.get("mode") == "cargo-catalog",
        "catalog_digest_loaded": metadata.get("mode") == "cargo-catalog",
        "cargo_page_contract": page_contract() if metadata.get("mode") == "cargo-page" else None,
        "proof_kind": metadata.get("proof_kind"),
        "cargo_contract": cargo_contract() if metadata.get("mode") == "industry-cargo" else None,
        "inventory_session": inventory_contract()
        if metadata.get("mode") == "industry-inventory"
        else None,
        "launches": 0,
        "connections": 0,
        "requests": 0,
    }


def preflight_prepared(prepared: PreparedProof, backend) -> dict:
    result = validate_native_inputs(prepared)
    backend.preflight(prepared)
    if result["proof_kind"] == "structural-world":
        from .structural_attempt import StructuralProductionRunner

        result.update(StructuralProductionRunner(prepared, backend).launch_boundary())
        result.update(
            structural_session_loaded=True,
            phase_barriers_loaded=True,
            referential_validation_loaded=True,
            structural_digest_loaded=True,
            max_application_requests=96,
            max_response_bytes=49152,
            lifecycle_overhead_frames=6,
        )
    reservation = EndpointReservation.allocate(*prepared.endpoints)
    try:
        result["endpoints_reserved"] = [reservation.game_port, reservation.admin_port]
    finally:
        reservation.close()
    return result
