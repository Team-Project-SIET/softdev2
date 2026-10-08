"""Immutable combined contract, exact destination, clock and continuous owner gates."""

import hashlib
import json

from .economy_authority import economy_authority, economy_clock_contract
from .enrichment_preparation import checkpoint_head
from .harness import BINARY_SHA256, PROJECT, sha256, write_json
from .production_preparation import authority_files as production_authority_files
from .raw_production_contract import (
    RAW_PRODUCTION_ATTEMPT_DIRECTORY,
    RAW_PRODUCTION_MODEL,
    RAW_PRODUCTION_REVISION,
    raw_production_contract,
    raw_production_contract_digest,
    raw_production_first_request,
)
from .raw_production_lineage import capture_lineage, lineage_rows, validate_lineage
from .structural_preparation import configuration_identity

PROVEN_BRIDGE_DIGEST = "cee002001d0a7a69c899e94c5c2cf77893a507e69686f4ac2e6d71effe94c58a"


def authority_files():
    files = production_authority_files()
    files.update(economy_authority()["files"])
    for name in (
        "docs/complete-raw-industry-production.md",
        "docs/complete-raw-industry-production-proof-preparation.md",
        "docs/complete-raw-production-economy-window-authority.md",
        "tests/test_complete_raw_production.py",
        "tests/test_raw_production_contract.py",
        "tests/test_raw_production_proof.py",
    ):
        files[str(PROJECT / name)] = sha256(PROJECT / name)
    return files


def accounting_identity():
    files = {
        name: sha256(PROJECT / name)
        for name in (
            "app/simulation/openttd/secure_admin.py",
            "app/simulation/openttd/admin_session.py",
            "app/simulation/openttd/admin_protocol.py",
            "app/simulation/openttd/gamescript_transport.py",
            "app/simulation/openttd/proof/structural_contract.py",
            "app/simulation/openttd/proof/structural_native.py",
            "app/simulation/openttd/proof/raw_production_contract.py",
            "app/simulation/openttd/proof/raw_production_native.py",
        )
    }
    return dict(
        files=files,
        sha256=hashlib.sha256(
            json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    )


def check_raw_production_preparation(directory, *, official=False):
    if official and directory.parent != PROJECT / "artifacts/runtime":
        raise ValueError("Exact combined runtime destination root required")
    if directory.with_name(RAW_PRODUCTION_ATTEMPT_DIRECTORY).exists():
        raise ValueError("Combined attempt destination already consumed")
    capture_lineage(
        directory, RAW_PRODUCTION_REVISION, directory.with_name(RAW_PRODUCTION_ATTEMPT_DIRECTORY)
    )
    contract = raw_production_contract()
    if (contract["max_query_operations"], contract["max_total_post_auth_frames"]) != (5120, 5126):
        raise ValueError("Native combined frame derivation changed; no freeze")
    authority_files()


def freeze_raw_production_preparation(directory, frozen, bridge_digest):
    if bridge_digest != PROVEN_BRIDGE_DIGEST:
        raise ValueError("Proven production bridge unchanged identity required")
    write_json(directory / "raw-production-contract.json", raw_production_contract())
    write_json(directory / "structural-context.json", configuration_identity(directory))
    write_json(directory / "economy-authority.json", economy_authority())
    write_json(directory / "frame-accounting-identity.json", accounting_identity())
    files = authority_files()
    frozen.update(files)
    write_json(directory / "source-authority.json", dict(version="15.3", files=files))
    lineage = capture_lineage(
        directory, RAW_PRODUCTION_REVISION, directory.with_name(RAW_PRODUCTION_ATTEMPT_DIRECTORY)
    )
    write_json(directory / "attempt-lineage.json", lineage)
    from .raw_production_attempt import RawProductionProofState

    write_json(
        directory / "combined-lifecycle.json",
        dict(
            states=[s.name for s in RawProductionProofState],
            terminal_success="only after disposal + postrun integrity + COMPLETED",
            cleanup_authority="app.simulation.openttd.proof.ownership.finalize_cleanup",
        ),
    )
    history = json.loads((directory / "historical-integrity.json").read_text())
    path = directory / "PRELAUNCH.json"
    value = json.loads(path.read_text())
    value.update(
        state="PREPARED",
        attempt=lineage["attempt_number"],
        prelaunch_revision=RAW_PRODUCTION_REVISION,
        proof_model=RAW_PRODUCTION_MODEL,
        proof_kind="complete-raw-production",
        baseline_head=checkpoint_head(),
        checkpoint_head=checkpoint_head(),
        attempt_id=lineage["attempt_id"],
        predecessor_attempt_ids=[r["attempt_id"] for r in lineage_rows(lineage)],
        lineage_digest=lineage["lineage_digest"],
        attempt_directory=str(directory.with_name(RAW_PRODUCTION_ATTEMPT_DIRECTORY)),
        proof_config_sha256=raw_production_contract_digest(),
        frame_accounting_identity=accounting_identity()["sha256"],
        economy_authority_digest=economy_authority()["sha256"],
        bridge_digest=bridge_digest,
        protected_unique_count=history["unique_count"],
        protected_manifest_sha256=history["sha256"],
        archived_credential_identity_count=len(history["credential_identities"]),
        source_input_count=0,
        semantic_authority=(
            "same-run complete raw production; zero rollovers; unqualified; non-atomic pre-decision"
        ),
        expected_future_evidence=[
            "proof-evidence.json",
            "proof-attempt.json",
            "final-report.md",
            "transactions.jsonl",
            "structural-session.json",
            "structural-observation.json",
            "structural-canonical.json",
            "structural-digest.json",
            "inventory-observation.json",
            "capability-observation.json",
            "catalog-observation.json",
            "production-session.json",
            "production-observation.json",
            "production-canonical.json",
            "combined-session.json",
            "process-lifecycle.json",
            "source-freeze-post.json",
            "admin-frame-accounting.json",
            "admin-auth-evidence.json",
            "protocol-evidence.json",
            "welcome-evidence.json",
            "stdout.log",
            "stderr.log",
            "artifact-manifest.sha256",
        ],
    )
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def validate_raw_production_preparation(prepared, metadata, bridge):
    directory = prepared.directory
    if (
        prepared.spec.identity.sha256 == BINARY_SHA256
        and directory.parent != PROJECT / "artifacts/runtime"
    ):
        raise ValueError("Exact combined native destination root required")
    lineage = json.loads((directory / "attempt-lineage.json").read_text())
    count = validate_lineage(
        directory,
        lineage,
        RAW_PRODUCTION_REVISION,
        directory.with_name(RAW_PRODUCTION_ATTEMPT_DIRECTORY),
    )
    history = json.loads((directory / "historical-integrity.json").read_text())
    if prepared.public_key in {r["public_key"] for r in history["credential_identities"]}:
        raise ValueError("Fresh combined credential required")
    config = prepared.spec.workspace.config.read_text()
    from configparser import ConfigParser

    parsed = ConfigParser(strict=True)
    parsed.read_string(config)
    if (
        parsed.get("economy", "timekeeping_units"),
        parsed.get("game_creation", "starting_year"),
    ) != ("0", "1950"):
        raise ValueError("Frozen new-world calendar economy clock required")
    from .raw_production_attempt import RawProductionProofState

    if (
        json.loads((directory / "raw-production-contract.json").read_text())
        != raw_production_contract()
        or json.loads((directory / "economy-authority.json").read_text()) != economy_authority()
        or json.loads((directory / "frame-accounting-identity.json").read_text())
        != accounting_identity()
        or json.loads((directory / "structural-context.json").read_text())
        != configuration_identity(directory)
        or json.loads((directory / "source-authority.json").read_text())["files"]
        != authority_files()
        or json.loads((directory / "combined-lifecycle.json").read_text())["states"]
        != [s.name for s in RawProductionProofState]
        or metadata.get("proof_config_sha256") != raw_production_contract_digest()
        or metadata.get("economy_authority_digest") != economy_authority()["sha256"]
        or metadata.get("frame_accounting_identity") != accounting_identity()["sha256"]
        or metadata.get("baseline_head") != checkpoint_head()
        or metadata.get("checkpoint_head") != checkpoint_head()
        or metadata.get("proof_kind") != "complete-raw-production"
        or metadata.get("attempt_id") != lineage["attempt_id"]
        or metadata.get("lineage_digest") != lineage["lineage_digest"]
        or metadata.get("predecessor_attempt_ids")
        != [r["attempt_id"] for r in lineage_rows(lineage)]
        or metadata.get("attempt_directory")
        != str(directory.with_name(RAW_PRODUCTION_ATTEMPT_DIRECTORY))
        or prepared.request != raw_production_first_request()
        or bridge["sha256"] != PROVEN_BRIDGE_DIGEST
        or metadata.get("bridge_digest") != bridge["sha256"]
        or "industry_production" not in bridge["commands"]
        or economy_clock_contract()["timekeeping_units"] != 0
    ):
        raise ValueError("Combined frozen clock/lifecycle/lineage/destination/accounting mismatch")
    return count
