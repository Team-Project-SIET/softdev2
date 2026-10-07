"""Freeze catalog-specific source, supporting native proof and exact lineage."""

import json
from pathlib import Path

from .cargo_page_contract import PAGE_BRIDGE_DIGEST
from .catalog_contract import (
    CATALOG_ATTEMPT_DIRECTORY,
    CATALOG_MODEL,
    CATALOG_REVISION,
    catalog_contract,
    catalog_contract_digest,
)
from .catalog_lineage import capture_lineage
from .enrichment_preparation import checkpoint_head
from .harness import BINARY_SHA256, PROJECT, sha256, write_json


def freeze_catalog_preparation(directory: Path, frozen: dict, bridge_digest: str):
    if bridge_digest != PAGE_BRIDGE_DIGEST:
        raise ValueError("Proven cargo bridge identity required")
    write_json(directory / "catalog-contract.json", catalog_contract())
    authority_path = PROJECT / "tests/reference/cargo_catalog_15_3/manifest.json"
    authority = json.loads(authority_path.read_text())
    for name, entry in authority["files"].items():
        p = PROJECT / name
        if sha256(p) != entry["sha256"]:
            raise ValueError("Cargo API authority changed")
        frozen[str(p)] = entry["sha256"]
    frozen[str(authority_path)] = sha256(authority_path)
    write_json(directory / "source-authority.json", authority)
    support: dict = dict(
        minimum_first_page_records=1,
        exact_cargo_ids_required=False,
        complete_catalog_proven=False,
        independent_second_source_catalog=None,
    )
    runtime = json.loads((directory / "runtime-identity.json").read_text())
    if runtime["sha256"] == BINARY_SHA256:
        old = PROJECT / "artifacts/runtime/openttd-15.3-cargo-page-real-attempt1"
        evidence = json.loads((old / "proof-evidence.json").read_text())
        verification = json.loads((old / "cargo-page-verification.json").read_text())
        if (
            evidence["status"] != "REAL_SUCCESS"
            or not verification["verified"]
            or verification["returned_count"] < 1
        ):
            raise ValueError("Successful nonempty native cargo-page baseline required")
        previous = json.loads((old / "sanitized-config.json").read_text())["openttd.cfg"]
        current = json.loads((directory / "sanitized-config.json").read_text())["openttd.cfg"]
        if previous.split("[game_creation]", 1)[1] != current.split("[game_creation]", 1)[1]:
            raise ValueError("Native runtime generation profile changed")
        for name in (
            "proof-evidence.json",
            "cargo-page-verification.json",
            "sanitized-config.json",
            "runtime-identity.json",
            "graphics-identity.json",
        ):
            frozen[str(old / name)] = sha256(old / name)
        support.update(
            native_binding_baseline=str(old),
            authority=(
                "successful nonempty native cargo page under identical pinned binary, "
                "graphics and generation profile; no exact full cargo-set expectation"
            ),
        )
    else:
        support["authority"] = "controlled fixture only"
    write_json(directory / "world-support.json", support)
    lineage = capture_lineage(
        directory, CATALOG_REVISION, directory.with_name(CATALOG_ATTEMPT_DIRECTORY)
    )
    write_json(directory / "attempt-lineage.json", lineage)
    history = json.loads((directory / "historical-integrity.json").read_text())
    p = directory / "PRELAUNCH.json"
    m = json.loads(p.read_text())
    m.update(
        state="PREPARED",
        mode="cargo-catalog",
        attempt=1,
        prelaunch_revision=CATALOG_REVISION,
        proof_model=CATALOG_MODEL,
        proof_kind="cargo-catalog",
        attempt_id=lineage["attempt_id"],
        predecessor_attempt_ids=[e["attempt_id"] for e in lineage["supersedes_prelaunch_attempts"]],
        lineage_digest=lineage["lineage_digest"],
        checkpoint_head=checkpoint_head(),
        attempt_directory=str(directory.with_name(CATALOG_ATTEMPT_DIRECTORY)),
        proof_config_sha256=catalog_contract_digest(),
        protected_unique_count=history["unique_count"],
        protected_manifest_sha256=history["sha256"],
        semantic_authority=(
            "complete bounded native cargo cursor traversal; no independent catalog equivalence"
        ),
    )
    m["expected_future_evidence"] = [
        "final-report.md",
        "proof-evidence.json",
        "catalog-observation.json",
        "catalog-session.json",
        "catalog-records.json",
        "catalog-digest.json",
        "page-requests.jsonl",
        "page-responses.jsonl",
        "page-receipts.jsonl",
        "network-page-evidence.jsonl",
        "gamescript-page-evidence.jsonl",
        "page-verifications.jsonl",
        "process-lifecycle.json",
        "proof-attempt.json",
        "source-freeze.json",
        "source-freeze-post.json",
        "historical-integrity.json",
        "attempt-lineage.json",
        "stdout.log",
        "stderr.log",
        "artifact-manifest.sha256",
    ]
    p.write_text(json.dumps(m, sort_keys=True, indent=2) + "\n")
    for p in directory.iterdir():
        if p.is_file() and p.name not in ("source-freeze.json", "artifact-manifest.sha256"):
            frozen[str(p)] = sha256(p)
    (directory / "source-freeze.json").write_text(
        json.dumps(dict(sorted(frozen.items())), sort_keys=True, indent=2) + "\n"
    )
