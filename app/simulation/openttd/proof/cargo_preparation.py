"""New native cargo proof freeze; historical inventory is provenance, not re-executed."""

import json
from pathlib import Path

from .cargo_contract import (
    CARGO_ATTEMPT_DIRECTORY,
    CARGO_BRIDGE_DIGEST,
    CARGO_MODEL,
    cargo_contract,
    cargo_contract_digest,
)
from .harness import BINARY_SHA256, PROJECT, sha256, write_json

CARGO_ARTIFACTS = [
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
    "industry-cargo-request.json",
    "industry-cargo-response.json",
    "transport-receipt.json",
    "industry-cargo-verification.json",
    "industry-cargo-contract.json",
    "source-authority.json",
    "inventory-provenance.json",
    "gamescript-proof-evidence.json",
    "gamescript-supporting.log",
    "network-evidence.json",
    "transaction-correlation.json",
    "process-lifecycle.json",
    "stdout.log",
    "stderr.log",
    "artifact-manifest.sha256",
]


def freeze_cargo_preparation(directory: Path, frozen: dict, bridge_digest: str) -> None:
    if bridge_digest != CARGO_BRIDGE_DIGEST:
        raise ValueError("Cargo bridge must match controlled capability implementation")
    write_json(directory / "industry-cargo-contract.json", cargo_contract())
    path = directory / "PRELAUNCH.json"
    metadata = json.loads(path.read_text())
    metadata.update(
        state="PREPARED",
        attempt=1,
        prelaunch_revision=1,
        proof_model=CARGO_MODEL,
        attempt_directory=str(directory.with_name(CARGO_ATTEMPT_DIRECTORY)),
        expected_future_evidence=CARGO_ARTIFACTS,
        real_application_requests=0,
        proof_config_sha256=cargo_contract_digest(),
        industry_id=0,
        semantic_authority=(
            "native structural cargo capability invariants; no independent second-source capability"
        ),
    )
    path.write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n")
    authority = {"version": "OpenTTD 15.3", "files": {}}
    for name in ("industry_cargo_15_3", "industry_page_bindings_15_3", "industry_evidence_15_3"):
        manifest = PROJECT / "tests/reference" / name / "manifest.json"
        data = json.loads(manifest.read_text())
        frozen[str(manifest)] = sha256(manifest)
        for relative, entry in data["files"].items():
            reference = PROJECT / relative
            if sha256(reference) != entry["sha256"]:
                raise ValueError("Cargo API/source authority changed")
            frozen[str(reference)] = entry["sha256"]
        authority["files"].update(data["files"])
    write_json(directory / "source-authority.json", authority)
    provenance = {
        "industry_id": 0,
        "inventory_digest": "dce9b4d257af150776e679b09c74880b918163b86ae5e5f9f6e30e35d26c865a",
        "claim": (
            "historically observed industry identity; no expected cargo IDs or"
            " independent capability inventory"
        ),
    }
    identity = json.loads((directory / "runtime-identity.json").read_text())
    if identity["sha256"] == BINARY_SHA256:
        previous = PROJECT / "artifacts/runtime/openttd-15.3-industry-inventory-real-attempt1"
        evidence = json.loads((previous / "proof-evidence.json").read_text())
        observation = json.loads((previous / "inventory-observation.json").read_text())
        if (
            evidence["status"] != "REAL_SUCCESS"
            or not observation["complete"]
            or not any(r["id"] == 0 for r in observation["records"])
        ):
            raise ValueError("Successful real inventory industry-0 provenance required")
        digest = json.loads((previous / "inventory-digest.json").read_text())
        if digest["sha256"] != provenance["inventory_digest"] or not digest["verified"]:
            raise ValueError("Historical inventory digest mismatch")
        records_path = previous / "inventory-records.json"
        if (
            sha256(records_path) != digest["sha256"]
            or json.loads(records_path.read_bytes()) != observation["records"]
        ):
            raise ValueError("Historical inventory records/digest mismatch")
        old = json.loads((previous / "sanitized-config.json").read_text())["openttd.cfg"]
        new = json.loads((directory / "sanitized-config.json").read_text())["openttd.cfg"]
        if old.split("[game_creation]", 1)[1] != new.split("[game_creation]", 1)[1]:
            raise ValueError("Deterministic generation configuration differs")
        for name in (
            "proof-evidence.json",
            "inventory-observation.json",
            "sanitized-config.json",
            "inventory-digest.json",
            "inventory-records.json",
        ):
            path = previous / name
            frozen[str(path)] = sha256(path)
        provenance["historical_directory"] = str(previous)
    else:
        provenance["claim"] = "controlled fixture only; not real inventory provenance"
    write_json(directory / "inventory-provenance.json", provenance)
    # Earlier root-level reports are historical inputs too, outside directory snapshots.
    for path in directory.parent.iterdir():
        if path.is_file():
            frozen[str(path)] = sha256(path)
    for path in directory.iterdir():
        if path.is_file() and path.name not in ("source-freeze.json", "artifact-manifest.sha256"):
            frozen[str(path)] = sha256(path)
    (directory / "source-freeze.json").write_text(
        json.dumps(dict(sorted(frozen.items())), sort_keys=True, indent=2) + "\n"
    )
