"""New immutable inventory prelaunch policy; no runtime activity."""

import json
from pathlib import Path

from .harness import BINARY_SHA256, PROJECT, sha256, write_json
from .inventory_contract import (
    INVENTORY_ATTEMPT_DIRECTORY,
    INVENTORY_BRIDGE_DIGEST,
    INVENTORY_MODEL,
    inventory_contract,
    inventory_contract_digest,
)

INVENTORY_ARTIFACTS = [
    "final-report.md",
    "runtime-identity.json",
    "graphics-identity.json",
    "bridge-package-identity.json",
    "source-freeze.json",
    "sanitized-config.json",
    "admin-auth-evidence.json",
    "protocol-evidence.json",
    "welcome-evidence.json",
    "inventory-session.json",
    "page-requests.jsonl",
    "page-responses.jsonl",
    "page-receipts.jsonl",
    "page-verifications.jsonl",
    "gamescript-page-evidence.jsonl",
    "inventory-observation.json",
    "inventory-digest.json",
    "process-lifecycle.json",
    "gamescript-supporting.log",
    "stdout.log",
    "stderr.log",
    "artifact-manifest.sha256",
]


def freeze_inventory_preparation(directory: Path, frozen: dict, bridge_digest: str) -> None:
    if bridge_digest != INVENTORY_BRIDGE_DIGEST:
        raise ValueError("Inventory bridge must match successful single-page Attempt #2")
    contract = inventory_contract()
    write_json(directory / "inventory-contract.json", contract)
    metadata_path = directory / "PRELAUNCH.json"
    metadata = json.loads(metadata_path.read_text())
    metadata.update(
        state="PREPARED",
        attempt=1,
        prelaunch_revision=1,
        proof_model=INVENTORY_MODEL,
        attempt_directory=str(directory.with_name(INVENTORY_ATTEMPT_DIRECTORY)),
        expected_future_evidence=INVENTORY_ARTIFACTS,
        real_application_requests=0,
        proof_config_sha256=inventory_contract_digest(),
        session_id=contract["session_id"],
        proof_page_size=2,
        semantic_authority=(
            "cursor-chain and record invariants; encrypted SERVER_WELCOME map bounds "
            "only; no independent inventory"
        ),
    )
    metadata_path.write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n")
    authority = {"version": "OpenTTD 15.3", "files": {}}
    for name in ("industry_page_bindings_15_3", "industry_evidence_15_3"):
        path = PROJECT / "tests/reference" / name / "manifest.json"
        data = json.loads(path.read_text())
        frozen[str(path)] = sha256(path)
        for relative, entry in data["files"].items():
            reference = PROJECT / relative
            if sha256(reference) != entry["sha256"]:
                raise ValueError("API/evidence source authority changed")
            frozen[str(reference)] = entry["sha256"]
        authority["files"].update(data["files"])
    write_json(directory / "source-authority.json", authority)
    supporting = {
        "expected_ids": [0, 1, 2],
        "claim": "historical support only; future actual multi-page traversal required",
    }
    identity = json.loads((directory / "runtime-identity.json").read_text())
    if identity["sha256"] == BINARY_SHA256:
        previous = PROJECT / "artifacts/runtime/openttd-15.3-industry-page-real-attempt2"
        evidence = json.loads((previous / "proof-evidence.json").read_text())
        if evidence["status"] != "REAL_SUCCESS":
            raise ValueError("Successful historical world support required")
        old = json.loads((previous / "sanitized-config.json").read_text())["openttd.cfg"]
        new = json.loads((directory / "sanitized-config.json").read_text())["openttd.cfg"]
        if old.split("[game_creation]", 1)[1] != new.split("[game_creation]", 1)[1]:
            raise ValueError("Deterministic generation configuration differs")
        for name in ("proof-evidence.json", "sanitized-config.json", "industry-page-response.json"):
            path = previous / name
            frozen[str(path)] = sha256(path)
        supporting["historical_directory"] = str(previous)
    else:
        supporting["claim"] = "controlled fixture only; not real-world evidence"
    write_json(directory / "world-support.json", supporting)
    for path in directory.iterdir():
        if path.is_file() and path.name not in ("source-freeze.json", "artifact-manifest.sha256"):
            frozen[str(path)] = sha256(path)
    (directory / "source-freeze.json").write_text(
        json.dumps(dict(sorted(frozen.items())), sort_keys=True, indent=2) + "\n"
    )
