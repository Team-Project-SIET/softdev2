"""Immutable qualification contract, exact destination and continuous owner gates."""

import hashlib
import json

from .endpoints import endpoint_cleanup_contract, kernel_socket_rows
from .enrichment_preparation import checkpoint_head
from .harness import BINARY_SHA256, PROJECT, sha256, write_json
from .production_preparation import authority_files as production_authority_files
from .qualification_authority import bridge_digest as expected_bridge_digest
from .qualification_authority import qualification_authority as economy_authority
from .qualification_contract import (
    ATTEMPT_DIRECTORY,
    MODEL,
    REVISION,
    digest,
    first_request,
    qualification_contract,
)
from .qualification_lineage import derive_next_attempt, lineage_rows, validate_lineage
from .structural_preparation import configuration_identity


def authority_files():
    files = production_authority_files()
    files.update(economy_authority()["files"])
    for name in (
        "docs/industry-production-two-rollover-qualification.md",
        "docs/two-rollover-qualification-proof-preparation.md",
        "app/simulation/openttd/qualification_clock.py",
        "app/simulation/openttd/qualification_bridge.nut",
        "tests/test_qualification_coordinator.py",
        "tests/test_qualification_preparation.py",
        "tests/test_qualification_dispatch_repair.py",
        "tests/test_historical_attempt_lineage.py",
        "tests/test_proof_endpoints.py",
        "docs/two-rollover-qualification-attempt1-diagnosis.md",
        "docs/two-rollover-qualification-endpoint-cleanup.md",
        "tests/reference/qualification_dispatch_15_3/manifest.json",
        "tests/reference/qualification_dispatch_15_3/sqlexer.cpp",
        "tests/reference/qualification_dispatch_15_3/sqcompiler.cpp",
        "tests/test_two_rollover_qualification.py",
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
            "app/simulation/openttd/proof/qualification_contract.py",
            "app/simulation/openttd/proof/qualification_accounting.py",
            "app/simulation/openttd/qualification_policy.py",
            "app/simulation/openttd/qualification_session.py",
            "app/simulation/openttd/proof/qualification_native.py",
        )
    }
    return dict(
        files=files,
        sha256=hashlib.sha256(
            json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    )


def check_qualification_preparation(directory, *, official=False):
    if official and directory.parent != PROJECT / "artifacts/runtime":
        raise ValueError("Exact combined runtime destination root required")
    if directory.with_name(ATTEMPT_DIRECTORY).exists():
        raise ValueError("Combined attempt destination already consumed")
    derive_next_attempt(directory, REVISION, directory.with_name(ATTEMPT_DIRECTORY))
    contract = qualification_contract()
    if (contract["resources"]["query_operations"], contract["resources"]["post_auth_frames"]) != (
        9088,
        9094,
    ):
        raise ValueError("Native combined frame derivation changed; no freeze")
    authority_files()


def freeze_qualification_preparation(directory, frozen, bridge_digest):
    if bridge_digest != expected_bridge_digest():
        raise ValueError("Exact derived qualification bridge identity required")
    write_json(directory / "qualification-contract.json", qualification_contract())
    write_json(directory / "endpoint-cleanup-contract.json", endpoint_cleanup_contract())
    write_json(directory / "structural-context.json", configuration_identity(directory))
    write_json(directory / "qualification-native-authority.json", economy_authority())
    write_json(directory / "frame-accounting-identity.json", accounting_identity())
    files = authority_files()
    frozen.update(files)
    write_json(directory / "source-authority.json", dict(version="15.3", files=files))
    lineage = derive_next_attempt(directory, REVISION, directory.with_name(ATTEMPT_DIRECTORY))
    write_json(directory / "attempt-lineage.json", lineage)
    from .qualification_attempt import QualificationProofState

    write_json(
        directory / "qualification-lifecycle.json",
        dict(
            states=[s.name for s in QualificationProofState],
            terminal_success="native lifecycle only after disposal + postrun integrity + COMPLETED",
            overall_acceptance="native success AND mandatory offline verification success",
            cleanup_authority="app.simulation.openttd.proof.ownership.finalize_cleanup",
        ),
    )
    history = json.loads((directory / "historical-integrity.json").read_text())
    path = directory / "PRELAUNCH.json"
    value = json.loads(path.read_text())
    value.update(
        state="PREPARED",
        attempt=lineage["attempt_number"],
        prelaunch_revision=REVISION,
        proof_model=MODEL,
        proof_kind="two-rollover-qualification",
        baseline_head=checkpoint_head(),
        checkpoint_head=checkpoint_head(),
        attempt_id=lineage["attempt_id"],
        predecessor_attempt_ids=[r["attempt_id"] for r in lineage_rows(lineage)],
        lineage_digest=lineage["lineage_digest"],
        attempt_directory=str(directory.with_name(ATTEMPT_DIRECTORY)),
        proof_config_sha256=digest(qualification_contract()),
        frame_accounting_identity=accounting_identity()["sha256"],
        native_authority_digest=economy_authority()["sha256"],
        bridge_digest=bridge_digest,
        polling_policy_digest=digest(qualification_contract()["resources"]),
        qualification_contract_digest=digest(qualification_contract()),
        protected_unique_count=history["unique_count"],
        protected_manifest_sha256=history["sha256"],
        archived_credential_identity_count=len(history["credential_identities"]),
        source_input_count=0,
        semantic_authority=(
            "two adjacent native rollovers; fresh complete M2 production; "
            "qualification admission; non-atomic pre-decision"
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
            "qualification-session.json",
            "qualified-month.json",
            "anchor/structural-observation.json",
            "final/structural-observation.json",
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


def validate_qualification_preparation(prepared, metadata, bridge):
    directory = prepared.directory
    if (
        json.loads((directory / "endpoint-cleanup-contract.json").read_text())
        != endpoint_cleanup_contract()
    ):
        raise ValueError("Frozen cleanup endpoint contract mismatch")
    kernel_socket_rows()  # Resolve Linux evidence authority before any launch.
    if (
        prepared.spec.identity.sha256 == BINARY_SHA256
        and directory.parent != PROJECT / "artifacts/runtime"
    ):
        raise ValueError("Exact combined native destination root required")
    lineage = json.loads((directory / "attempt-lineage.json").read_text())
    count = validate_lineage(
        directory,
        lineage,
        REVISION,
        directory.with_name(ATTEMPT_DIRECTORY),
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
    if (
        parsed.get("network", "min_active_clients") != "0"
        or parsed.get(
            "gui",
            "pause_on_newgame",
            fallback=parsed.get("misc", "pause_on_newgame", fallback="false"),
        )
        != "false"
        or parsed.get("difficulty", "max_no_competitors") != "0"
        or any(
            parsed.items(section)
            for section in ("newgrf", "newgrf-static")
            if parsed.has_section(section)
        )
    ):
        raise ValueError("Generated unpaused competitor/NewGRF-free qualification profile required")
    from .qualification_attempt import QualificationProofState

    if (
        json.loads((directory / "qualification-contract.json").read_text())
        != qualification_contract()
        or json.loads((directory / "qualification-native-authority.json").read_text())
        != economy_authority()
        or json.loads((directory / "frame-accounting-identity.json").read_text())
        != accounting_identity()
        or json.loads((directory / "structural-context.json").read_text())
        != configuration_identity(directory)
        or json.loads((directory / "source-authority.json").read_text())["files"]
        != authority_files()
        or json.loads((directory / "qualification-lifecycle.json").read_text())["states"]
        != [s.name for s in QualificationProofState]
        or metadata.get("polling_policy_digest") != digest(qualification_contract()["resources"])
        or metadata.get("qualification_contract_digest") != digest(qualification_contract())
        or metadata.get("proof_config_sha256") != digest(qualification_contract())
        or metadata.get("native_authority_digest") != economy_authority()["sha256"]
        or metadata.get("frame_accounting_identity") != accounting_identity()["sha256"]
        or metadata.get("baseline_head") != checkpoint_head()
        or metadata.get("checkpoint_head") != checkpoint_head()
        or metadata.get("proof_kind") != "two-rollover-qualification"
        or metadata.get("attempt_id") != lineage["attempt_id"]
        or metadata.get("lineage_digest") != lineage["lineage_digest"]
        or metadata.get("predecessor_attempt_ids")
        != [r["attempt_id"] for r in lineage_rows(lineage)]
        or metadata.get("attempt_directory") != str(directory.with_name(ATTEMPT_DIRECTORY))
        or prepared.request != first_request()
        or bridge["sha256"] != expected_bridge_digest()
        or metadata.get("bridge_digest") != bridge["sha256"]
        or "industry_production" not in bridge["commands"]
        or qualification_contract()["profile"]["timekeeping_units"] != 0
    ):
        raise ValueError("Combined frozen clock/lifecycle/lineage/destination/accounting mismatch")
    return count
