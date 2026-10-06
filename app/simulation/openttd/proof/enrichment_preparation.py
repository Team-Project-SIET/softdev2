"""New same-runtime enrichment freeze, with no historical inventory as query input."""

import json
from pathlib import Path

from .cargo_contract import CARGO_BRIDGE_DIGEST
from .cargo_preparation import freeze_cargo_preparation
from .enrichment_contract import (
    ENRICHMENT_ATTEMPT_DIRECTORY,
    ENRICHMENT_MODEL,
    ENRICHMENT_REVISION,
    enrichment_contract,
    enrichment_contract_digest,
)
from .enrichment_lineage import capture_lineage
from .harness import PROJECT, sha256, write_json

ENRICHMENT_ARTIFACTS = [
    "final-report.md",
    "proof-evidence.json",
    "runtime-identity.json",
    "graphics-identity.json",
    "bridge-package-identity.json",
    "source-freeze.json",
    "attempt-lineage.json",
    "proof-attempt.json",
    "sanitized-config.json",
    "admin-auth-evidence.json",
    "protocol-evidence.json",
    "welcome-evidence.json",
    "enrichment-contract.json",
    "enrichment-session.json",
    "inventory-session.json",
    "page-requests.jsonl",
    "page-responses.jsonl",
    "page-receipts.jsonl",
    "page-verifications.jsonl",
    "gamescript-page-evidence.jsonl",
    "inventory-observation.json",
    "inventory-digest.json",
    "capability-requests.jsonl",
    "capability-responses.jsonl",
    "capability-receipts.jsonl",
    "capability-verifications.jsonl",
    "gamescript-capability-evidence.jsonl",
    "capability-observation.json",
    "capability-digest.json",
    "enriched-observation.json",
    "gamescript-supporting.log",
    "process-lifecycle.json",
    "stdout.log",
    "stderr.log",
    "artifact-manifest.sha256",
]


def checkpoint_head():
    gitdir = PROJECT / ".git"
    if gitdir.is_file():
        gitdir = (PROJECT / gitdir.read_text().strip().split(": ", 1)[1]).resolve()
    value = (gitdir / "HEAD").read_text().strip()
    if not value.startswith("ref: "):
        return value
    ref = value[5:]
    common = gitdir
    if (gitdir / "commondir").exists():
        common = (gitdir / (gitdir / "commondir").read_text().strip()).resolve()
    for root in (gitdir, common):
        if (root / ref).exists():
            return (root / ref).read_text().strip()
        if (root / "packed-refs").exists():
            for line in (root / "packed-refs").read_text().splitlines():
                if line.endswith(" " + ref):
                    return line.split(" ", 1)[0]
    raise ValueError("Checkpoint HEAD unavailable")


def freeze_enrichment_preparation(directory: Path, frozen: dict, bridge_digest: str):
    # Reuse cargo API authority/runtime generation checks; historical inventory is support only.
    freeze_cargo_preparation(directory, frozen, bridge_digest)
    if bridge_digest != CARGO_BRIDGE_DIGEST:
        raise ValueError("Unchanged proven cargo bridge required")
    support = json.loads((directory / "inventory-provenance.json").read_text())
    support.pop("industry_id", None)
    support["claim"] = "historical deterministic world support only; never a source inventory input"
    write_json(directory / "world-support.json", support)
    for name in ("inventory-provenance.json", "industry-cargo-contract.json"):
        (directory / name).unlink()
        frozen.pop(str(directory / name), None)
    write_json(directory / "enrichment-contract.json", enrichment_contract())
    head = checkpoint_head()
    write_json(
        directory / "checkpoint.json",
        {"head": head, "policy": "record baseline only; no commit or checkpoint rewrite"},
    )
    path = directory / "PRELAUNCH.json"
    m = json.loads(path.read_text())
    m.update(
        prelaunch_revision=ENRICHMENT_REVISION,
        mode="industry-enrichment",
        proof_model=ENRICHMENT_MODEL,
        attempt_directory=str(directory.with_name(ENRICHMENT_ATTEMPT_DIRECTORY)),
        expected_future_evidence=ENRICHMENT_ARTIFACTS,
        session_id=enrichment_contract()["session_id"],
        proof_config_sha256=enrichment_contract_digest(),
        checkpoint_head=head,
        semantic_authority=(
            "same-run complete cursor chain and capability coverage; no independent second source"
        ),
    )
    m.pop("industry_id", None)
    lineage = capture_lineage(
        directory, ENRICHMENT_REVISION, directory.with_name(ENRICHMENT_ATTEMPT_DIRECTORY)
    )
    write_json(directory / "attempt-lineage.json", lineage)
    m["attempt_id"] = lineage["attempt_id"]
    m["lineage_digest"] = lineage["lineage_digest"]
    m["predecessor_attempt_ids"] = [
        row["attempt_id"] for row in lineage["supersedes_prelaunch_attempts"]
    ]
    history = json.loads((directory / "historical-integrity.json").read_text())
    m["protected_unique_count"] = history["unique_count"]
    m["protected_manifest_sha256"] = history["sha256"]
    path.write_text(json.dumps(m, sort_keys=True, indent=2) + "\n")
    for path in directory.iterdir():
        if path.is_file() and path.name not in ("source-freeze.json", "artifact-manifest.sha256"):
            frozen[str(path)] = sha256(path)
    (directory / "source-freeze.json").write_text(
        json.dumps(dict(sorted(frozen.items())), sort_keys=True, indent=2) + "\n"
    )
