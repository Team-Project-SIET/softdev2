"""Immutable production freeze and historical-only deterministic target authority."""

import hashlib
import json
from pathlib import Path

from .enrichment_preparation import checkpoint_head
from .harness import BINARY_SHA256, PROJECT, manifest, sha256, write_json
from .production_contract import (
    PRODUCTION_ATTEMPT_DIRECTORY,
    PRODUCTION_MODEL,
    PRODUCTION_REQUEST,
    PRODUCTION_REVISION,
    production_contract,
    production_contract_digest,
)
from .production_lineage import capture_lineage, lineage_rows, validate_lineage
from .production_verification import verify_industry_production

HISTORICAL_STRUCTURAL = PROJECT / "artifacts/runtime/openttd-15.3-structural-world-real-attempt1"


def select_historical_target(directory: Path = HISTORICAL_STRUCTURAL):
    """Validate retained successful REAL same-run structural evidence, never a fixture."""
    if directory.resolve() != HISTORICAL_STRUCTURAL.resolve():
        raise ValueError("Synthetic/alternate target authority rejected")
    if (directory / "artifact-manifest.sha256").read_text() != manifest(directory):
        raise ValueError("Historical structural manifest mismatch")
    proof = json.loads((directory / "proof-evidence.json").read_text())
    observation = json.loads((directory / "structural-observation.json").read_text())
    runtime = json.loads((directory / "runtime-identity.json").read_text())
    caps = json.loads((directory / "capability-observation.json").read_text())
    canonical = json.loads((directory / "structural-canonical.json").read_text())
    digest = json.loads((directory / "structural-digest.json").read_text())["sha256"]
    if (
        proof["status"] != "REAL_SUCCESS"
        or (proof["launches"], proof["connections"], proof["requests_sent"]) != (1, 1, 21)
        or not all(
            observation[k] is True
            for k in ("complete", "same_process", "same_connection", "capability_complete")
        )
        or runtime["sha256"] != BINARY_SHA256
        or runtime["version"] != "15.3"
        or sha256(directory / "structural-canonical.json") != digest
        or observation["structural_world_digest"] != digest
        or not caps["complete"]
        or canonical["capability_digest"] != caps["semantic_digest"]
        or hashlib.sha256(
            json.dumps(caps["semantic_observation"], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        != caps["semantic_digest"]
    ):
        raise ValueError("Successful real structural target provenance required")
    pairs = sorted(
        (r["industry_id"], c) for r in caps["semantic_observation"] for c in r["produces"]
    )
    if not pairs:
        raise ValueError("No produced industry/cargo pair in retained real structural evidence")
    industry, cargo = pairs[0]
    return dict(
        industry_id=industry,
        cargo_id=cargo,
        structural_digest=digest,
        supporting_directory=str(directory),
        supporting_files={
            n: sha256(directory / n)
            for n in (
                "proof-evidence.json",
                "structural-observation.json",
                "structural-canonical.json",
                "structural-digest.json",
                "capability-observation.json",
                "artifact-manifest.sha256",
            )
        },
        rule="lexicographically first industry_id,cargo_id in produces",
        eligibility="historical proven structural evidence",
        same_run_structural_provenance="NOT PROVEN BY THIS SLICE",
    )


def validate_target(value):
    if value != select_historical_target() or (value["industry_id"], value["cargo_id"]) != (
        PRODUCTION_REQUEST.industry_id,
        PRODUCTION_REQUEST.cargo_id,
    ):
        raise ValueError("Frozen produced target differs from historical first pair")


def authority_files():
    files = {}
    for name in (
        "industry_production_15_3",
        "industry_production_proof_15_3",
        "industry_evidence_15_3",
        "cargo_catalog_15_3",
        "industry_cargo_15_3",
        "industry_page_bindings_15_3",
    ):
        path = PROJECT / "tests/reference" / name / "manifest.json"
        authority = json.loads(path.read_text())
        files[str(path)] = sha256(path)
        for source, entry in authority["files"].items():
            if sha256(PROJECT / source) != entry["sha256"]:
                raise ValueError("Native 15.3 API source authority changed")
            files[str(PROJECT / source)] = entry["sha256"]
    for name in (
        "docs/industry-production-native-api-audit.md",
        "docs/industry-production-dynamic-supply-design.md",
        "docs/industry-production-real-proof-preparation.md",
        "tests/test_industry_production_proof.py",
        "tests/test_proof_cleanup_ownership.py",
        "docs/industry-production-cleanup-ownership-reconciliation.md",
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
            "app/simulation/openttd/proof/structural_contract.py",
            "app/simulation/openttd/proof/production_contract.py",
            "app/simulation/openttd/proof/production_native.py",
        )
    }
    return dict(
        files=files,
        sha256=hashlib.sha256(
            json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    )


def check_production_preparation(directory):
    production_contract()
    validate_target(select_historical_target())
    authority_files()
    destination = directory.with_name(PRODUCTION_ATTEMPT_DIRECTORY)
    if destination.exists():
        raise ValueError("Production destination already claimed")
    capture_lineage(directory, PRODUCTION_REVISION, destination)


def freeze_production_preparation(directory, frozen, bridge_digest):
    target = select_historical_target()
    validate_target(target)
    write_json(directory / "production-target.json", target)
    write_json(directory / "production-contract.json", production_contract())
    write_json(directory / "frame-accounting-identity.json", accounting_identity())
    authority = authority_files()
    frozen.update(authority)
    write_json(
        directory / "source-authority.json",
        dict(
            version="15.3",
            files=authority,
            bindings={
                "ScriptIndustry::IsValidIndustry": "GSIndustry.IsValidIndustry",
                "ScriptCargo::IsValidCargo": "GSCargo.IsValidCargo",
                "ScriptIndustry::GetLastMonthProduction": "GSIndustry.GetLastMonthProduction",
                "ScriptIndustry::GetLastMonthTransported": "GSIndustry.GetLastMonthTransported",
                "ScriptIndustry::GetLastMonthTransportedPercentage": (
                    "GSIndustry.GetLastMonthTransportedPercentage"
                ),
                "ScriptDate::GetCurrentDate": "GSDate.GetCurrentDate",
                "ScriptLog::Info": "GSLog.Info",
                "ScriptAdmin::Send": "GSAdmin.Send",
            },
        ),
    )
    lineage = capture_lineage(
        directory, PRODUCTION_REVISION, directory.with_name(PRODUCTION_ATTEMPT_DIRECTORY)
    )
    write_json(directory / "attempt-lineage.json", lineage)
    history = json.loads((directory / "historical-integrity.json").read_text())
    path = directory / "PRELAUNCH.json"
    metadata = json.loads(path.read_text())
    metadata.update(
        state="PREPARED",
        attempt=lineage["attempt_number"],
        prelaunch_revision=PRODUCTION_REVISION,
        proof_model=PRODUCTION_MODEL,
        proof_kind="industry-production",
        checkpoint_head=checkpoint_head(),
        baseline_head=checkpoint_head(),
        attempt_id=lineage["attempt_id"],
        lineage_digest=lineage["lineage_digest"],
        predecessor_attempt_ids=[r["attempt_id"] for r in lineage_rows(lineage)],
        attempt_directory=str(directory.with_name(PRODUCTION_ATTEMPT_DIRECTORY)),
        proof_config_sha256=production_contract_digest(),
        frame_accounting_identity=accounting_identity()["sha256"],
        protected_unique_count=history["unique_count"],
        protected_manifest_sha256=history["sha256"],
        bridge_digest=bridge_digest,
        archived_credential_identity_count=len(history["credential_identities"]),
        historical_structural_digest=target["structural_digest"],
        industry_id=target["industry_id"],
        cargo_id=target["cargo_id"],
        semantic_authority="raw V1 native metrics only; unqualified; historical target eligibility",
        expected_future_evidence=[
            "PRELAUNCH.json",
            "request.json",
            "production-target.json",
            "production-contract.json",
            "source-authority.json",
            "source-freeze.json",
            "path-ownership.json",
            "runtime-materializations.json",
            "historical-integrity.json",
            "attempt-lineage.json",
            "frame-accounting-identity.json",
            "runtime-identity.json",
            "graphics-identity.json",
            "bridge-package-identity.json",
            "sanitized-config.json",
            "admin-auth-evidence.json",
            "protocol-evidence.json",
            "welcome-evidence.json",
            "stdout.log",
            "stderr.log",
            "launch-claim.json",
            "final-report.md",
            "proof-evidence.json",
            "production-verification.json",
            "production-response.json",
            "transport-receipt.json",
            "gamescript-proof-evidence.json",
            "gamescript-supporting.log",
            "network-evidence.json",
            "admin-frame-accounting.json",
            "process-lifecycle.json",
            "proof-attempt.json",
            "artifact-manifest.sha256",
        ],
    )
    metadata["source_input_count"] = len(
        set(frozen)
        | {
            str(p)
            for p in directory.iterdir()
            if p.is_file() and p.name not in ("source-freeze.json", "artifact-manifest.sha256")
        }
    )
    path.write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n")
    for path in directory.iterdir():
        if path.is_file() and path.name not in ("source-freeze.json", "artifact-manifest.sha256"):
            frozen[str(path)] = sha256(path)
    (directory / "source-freeze.json").write_text(
        json.dumps(dict(sorted(frozen.items())), sort_keys=True, indent=2) + "\n"
    )


def validate_production_preparation(prepared, metadata, bridge):
    directory = prepared.directory
    lineage = json.loads((directory / "attempt-lineage.json").read_text())
    if (
        prepared.spec.identity.sha256 == BINARY_SHA256
        and directory.parent != PROJECT / "artifacts/runtime"
    ):
        raise ValueError("Exact production runtime destination required")
    count = validate_lineage(
        directory, lineage, PRODUCTION_REVISION, directory.with_name(PRODUCTION_ATTEMPT_DIRECTORY)
    )
    validate_target(json.loads((directory / "production-target.json").read_text()))
    history = json.loads((directory / "historical-integrity.json").read_text())
    if prepared.public_key in {r["public_key"] for r in history["credential_identities"]}:
        raise ValueError("Fresh production credential required")
    if (
        json.loads((directory / "production-contract.json").read_text()) != production_contract()
        or metadata.get("proof_config_sha256") != production_contract_digest()
        or metadata.get("attempt_directory")
        != str(directory.with_name(PRODUCTION_ATTEMPT_DIRECTORY))
        or metadata.get("proof_kind") != "industry-production"
        or metadata.get("checkpoint_head") != checkpoint_head()
        or metadata.get("attempt_id") != lineage["attempt_id"]
        or metadata.get("lineage_digest") != lineage["lineage_digest"]
        or metadata.get("predecessor_attempt_ids")
        != [r["attempt_id"] for r in lineage_rows(lineage)]
        or prepared.request != PRODUCTION_REQUEST
        or bridge["sha256"] != metadata.get("bridge_digest")
        or "industry_production" not in bridge["commands"]
        or json.loads((directory / "frame-accounting-identity.json").read_text())
        != accounting_identity()
        or json.loads((directory / "source-authority.json").read_text())["files"]
        != authority_files()
        or not callable(verify_industry_production)
    ):
        raise ValueError(
            "Production frozen target/destination/lineage/validator/accounting mismatch"
        )
    from .production_attempt import ProductionLifecycle

    ProductionLifecycle()
    return count
