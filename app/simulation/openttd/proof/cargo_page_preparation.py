"""Frozen first native cargo page, explicit provenance and proof-kind lineage."""

import json
from pathlib import Path

from .cargo_page_contract import (
    PAGE_ATTEMPT_DIRECTORY,
    PAGE_BRIDGE_DIGEST,
    PAGE_MODEL,
    PAGE_REVISION,
    page_contract,
    page_contract_digest,
)
from .cargo_page_lineage import capture_lineage
from .enrichment_preparation import checkpoint_head
from .harness import BINARY_SHA256, PROJECT, sha256, write_json


def freeze_page_preparation(directory: Path, frozen: dict, bridge_digest: str):
    if bridge_digest != PAGE_BRIDGE_DIGEST:
        raise ValueError("Controlled cargo-page bridge identity required")
    contract = page_contract()
    write_json(directory / "cargo-page-contract.json", contract)
    authority = json.loads(
        (PROJECT / "tests/reference/cargo_catalog_15_3/manifest.json").read_text()
    )
    for relative, entry in authority["files"].items():
        p = PROJECT / relative
        if sha256(p) != entry["sha256"]:
            raise ValueError("Cargo API source authority changed")
        frozen[str(p)] = entry["sha256"]
    authority_path = PROJECT / "tests/reference/cargo_catalog_15_3/manifest.json"
    frozen[str(authority_path)] = sha256(authority_path)
    write_json(directory / "source-authority.json", authority)
    support = dict(policy=contract["empty_policy"], minimum_records=1)
    runtime = json.loads((directory / "runtime-identity.json").read_text())
    if runtime["sha256"] == BINARY_SHA256:
        previous = (
            PROJECT / "artifacts/runtime/openttd-15.3-industry-capability-enrichment-real-attempt1"
        )
        observation = json.loads((previous / "capability-observation.json").read_text())
        evidence = json.loads((previous / "proof-evidence.json").read_text())
        if (
            evidence["status"] != "REAL_SUCCESS"
            or not observation["complete"]
            or not any(r["produces"] or r["accepts"] for r in observation["records"])
        ):
            raise ValueError("Active cargo native historical support missing")
        old = json.loads((previous / "sanitized-config.json").read_text())["openttd.cfg"]
        new = json.loads((directory / "sanitized-config.json").read_text())["openttd.cfg"]
        if old.split("[game_creation]", 1)[1] != new.split("[game_creation]", 1)[1]:
            raise ValueError("Frozen generation profile differs")
        for name in ("capability-observation.json", "proof-evidence.json", "sanitized-config.json"):
            p = previous / name
            frozen[str(p)] = sha256(p)
        support["historical_directory"] = str(previous)
        support["authority"] = (
            "prior successful native valid cargo reads plus identical pinned "
            "binary/OpenGFX/generation configuration; not independent same-run equivalence"
        )
    else:
        support["authority"] = "controlled fixture only; not native active-cargo authority"
    write_json(directory / "world-support.json", support)
    lineage = capture_lineage(directory, PAGE_REVISION, directory.with_name(PAGE_ATTEMPT_DIRECTORY))
    write_json(directory / "attempt-lineage.json", lineage)
    history = json.loads((directory / "historical-integrity.json").read_text())
    path = directory / "PRELAUNCH.json"
    meta = json.loads(path.read_text())
    meta.update(
        state="PREPARED",
        mode="cargo-page",
        attempt=1,
        prelaunch_revision=PAGE_REVISION,
        proof_model=PAGE_MODEL,
        proof_kind="cargo-page",
        attempt_id=lineage["attempt_id"],
        predecessor_attempt_ids=[r["attempt_id"] for r in lineage["supersedes_prelaunch_attempts"]],
        lineage_digest=lineage["lineage_digest"],
        checkpoint_head=checkpoint_head(),
        attempt_directory=str(directory.with_name(PAGE_ATTEMPT_DIRECTORY)),
        proof_config_sha256=page_contract_digest(),
        protected_unique_count=history["unique_count"],
        protected_manifest_sha256=history["sha256"],
        semantic_authority=(
            "native single-page structural metadata and cursor semantics; no "
            "independent catalog; no complete catalog claim"
        ),
        expected_future_evidence=[
            "final-report.md",
            "proof-evidence.json",
            "cargo-page-request.json",
            "cargo-page-response.json",
            "cargo-page-verification.json",
            "transport-receipt.json",
            "network-evidence.json",
            "gamescript-proof-evidence.json",
            "transaction-correlation.json",
            "process-lifecycle.json",
            "source-freeze.json",
            "source-freeze-post.json",
            "historical-integrity.json",
            "attempt-lineage.json",
            "proof-attempt.json",
            "runtime-identity.json",
            "graphics-identity.json",
            "bridge-package-identity.json",
            "sanitized-config.json",
            "source-authority.json",
            "world-support.json",
            "cargo-page-contract.json",
            "stdout.log",
            "stderr.log",
            "artifact-manifest.sha256",
        ],
    )
    path.write_text(json.dumps(meta, sort_keys=True, indent=2) + "\n")
    for p in directory.iterdir():
        if p.is_file() and p.name not in ("source-freeze.json", "artifact-manifest.sha256"):
            frozen[str(p)] = sha256(p)
    (directory / "source-freeze.json").write_text(
        json.dumps(dict(sorted(frozen.items())), sort_keys=True, indent=2) + "\n"
    )
