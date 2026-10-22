"""Prepared (never executed) Seed 17 Tile Classification V2 capture staging.

This module stages ONE independently reviewable census attempt:

- it composes the additive schema-2 classification package without touching
  the frozen v1 compositions (raw-base marker rename is performed in memory
  only, exactly like :mod:`terrain_classification_bridge`),
- it records the retained Seed 17 reference identities, the deterministic
  bounded request plan and every execution budget as a
  ``PENDING_AUTHORIZATION`` candidate, and
- it refuses to prepare whenever any staging seam is missing or contradictory
  (retained evidence absent, plan shape wrong, package composition drifted).

Offline only: no OpenTTD launch, no AdminPort connection, no authorization
consumption, no historical evidence mutation. Authorization statements in the
candidate describe a future operator action and consume nothing here.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from ..supplemental_planning_facts import SupplementalPlanningFacts
from ..terrain_bridge import terrain_bridge_source
from ..terrain_classification_bridge import (
    classification_capture_consistency,
    classification_package_bytes,
    classification_package_digest,
)
from ..tile_classification import (
    CLASSIFICATION_PAGE_LIMIT,
    CLASSIFICATION_SCHEMA_VERSION,
    CLASSIFICATION_TOTAL_RESPONSE_BYTES_LIMIT,
    classification_plan,
)
from .harness import (
    BINARY,
    BINARY_SHA256,
    PROJECT,
    sha256,
    verify_freeze,
    write_json,
)
from .harness import (
    source_freeze as shared_source_freeze,
)

SEED17_RUN = PROJECT / "artifacts/demos/playable-demo-698799a2dfb146948fd2983ff2032253"
ARTIFACT_ROOT = PROJECT / "artifacts/demos"
CLASSIFICATION_REQUEST_ID = "seed17-tile-classification-v2"
CAPTURE_KIND = "tile-classification-capture"
STATE = "PENDING_AUTHORIZATION"

WELCOME_IDENTITY_KEYS = ("seed", "width", "height", "landscape", "revision", "start_day")

FROZEN_CLASSIFICATION_SOURCES = (
    "app/simulation/openttd/tile_classification.py",
    "app/simulation/openttd/terrain_classification.nut",
    "app/simulation/openttd/terrain_classification_bridge.py",
    "app/planning/p08_terrain.py",
    "app/planning/construction_readiness.py",
    "app/simulation/openttd/proof/terrain_classification_preparation.py",
)

RETAINED_REFERENCES = (
    "network-facts-0.json",
    "runtime-identity.json",
    "world-planning-observation.json",
    "random-generation-request.json",
)

# Per-page request/response envelope budgets (mirroring retained v1 budgets).
OBSERVATION_SECONDS = 600
GSADMIN_BYTES = 508


def retained_facts() -> SupplementalPlanningFacts:
    source = SEED17_RUN / "network-facts-0.json"
    if not source.is_file():
        raise ValueError(f"retained Seed 17 evidence missing: {source}")
    return SupplementalPlanningFacts.model_validate_json(source.read_bytes())


def retained_welcome() -> dict:
    source = SEED17_RUN / "runtime-identity.json"
    if not source.is_file():
        raise ValueError(f"retained runtime identity missing: {source}")
    value = json.loads(source.read_bytes())
    welcome = value.get("welcome")
    if not isinstance(welcome, dict):
        raise ValueError("retained runtime identity carries no welcome record")
    return welcome


def request_plan() -> tuple[bytes, ...]:
    """Exact per-page request payloads of the deterministic 450-tile census."""
    facts = retained_facts()
    region = facts.region
    total = region.width * region.height
    if total != len(facts.tiles):
        raise ValueError("retained census region does not match its tile facts")
    plan = classification_plan(region, CLASSIFICATION_REQUEST_ID)
    payload = tuple(request.to_bytes() for request in plan)
    if len(payload) > CLASSIFICATION_PAGE_LIMIT:
        raise ValueError("classification request plan exceeds the page budget")
    return payload


def launch_command_template(config_path: str) -> dict:
    """Exact command shape; only freshly staged endpoints may vary at runtime.

    The argument order mirrors the retained Seed 17 prelaunch record bitwise
    (the flags that produced that world); the reserved endpoints and the
    staged isolated configuration path are re-materialized at the execution
    preflight and then recorded verbatim in the attempt record.
    """
    return {
        "binary": str(BINARY),
        "argv": [
            str(BINARY),
            "-D127.0.0.1:{reserved_game_port}",
            "-c",
            config_path,
            "-x",
            "-X",
            "-G",
            "17",
            "-g",
            "-dscript=4,grf=1,net=3",
        ],
        "fixed_arguments": ("-x", "-X", "-G", "17", "-g", "-dscript=4,grf=1,net=3"),
        "variables": (
            "-D endpoints are freshly reserved at the execution preflight",
            "-c points at a freshly staged isolated configuration directory",
        ),
        "binary_sha256": BINARY_SHA256,
    }


def cleanup_procedure() -> tuple[str, ...]:
    return (
        "close every reserved endpoint socket owned by the attempt",
        "record the exact native command actually launched in the attempt record",
        "stop the runtime process if any; retain failure.sav and frame records when present",
        "remove the freshly staged isolated runtime directory; keep all classification "
        "request/response artifacts and receipts byte-exact",
        "leave any claim or authorization ledger untouched unless the capture launched "
        "under its own fresh one-shot record",
    )


def validate_staging_seams() -> dict[str, str]:
    """Fail preparation on missing or contradictory composition seams."""
    package = classification_package_bytes()
    for name, data in package.items():
        if not data:
            raise ValueError(f"staged package file is empty: {name}")
    composed = package["main.nut"].decode()
    if composed.count("class NoMutationBridge extends GSController") != 0:
        raise ValueError("renamed raw bridge marker leaked into the staged package")
    if composed.count("class RawObservationBridge extends GSController") != 1:
        raise ValueError("raw bridge marker rename drifted")
    if composed.count("class NoMutationBridge extends TerrainClassificationBridge {}") != 1:
        raise ValueError("classification handler seam missing from the staged package")
    for prohibited in ("RaiseTile", "LowerTile", "LevelTiles"):
        if prohibited in composed:
            raise ValueError(f"staged package carries a prohibited mutation seam: {prohibited}")
    if "request.len()!=6" not in composed:
        raise ValueError("classification request shape gate missing from the staged package")
    # The v1 composition must remain byte-identical to its frozen authority.
    v1 = terrain_bridge_source()
    if not v1 or v1.count("class RawObservationBridge extends GSController") != 1:
        raise ValueError("v1 terrain composition changed")
    if v1.count("class NoMutationBridge extends TerrainBridge {}") != 1:
        raise ValueError("v1 terrain composition changed")
    consistency = classification_capture_consistency()
    if consistency["schema_version"] != CLASSIFICATION_SCHEMA_VERSION:
        raise ValueError("classification composition lost its schema version")
    return {
        "classification_package_digest": classification_package_digest(package),
        "v1_terrain_composition_sha256": hashlib.sha256(v1.encode()).hexdigest(),
        "main_nut_bytes": str(len(package["main.nut"])),
        "info_nut_sha256": hashlib.sha256(package["info.nut"]).hexdigest(),
    }


def classification_source_freeze() -> dict[str, str]:
    """Runtime inventory plus the additive classification sources."""
    frozen = shared_source_freeze()
    for relative in FROZEN_CLASSIFICATION_SOURCES:
        path = (PROJECT / relative).resolve()
        frozen[str(path)] = sha256(path)
    return frozen


@dataclass(frozen=True)
class PreparedCapture:
    """Offline prepared candidate; launching is exclusively a future action."""

    directory: Path
    attempt_identity: str
    package_digest: str
    pages: int
    tiles: int

    @property
    def candidate(self) -> dict:
        stored = json.loads((self.directory / "CANDIDATE.json").read_bytes())
        if (
            stored.get("kind") != CAPTURE_KIND
            or stored.get("state") != STATE
            or stored.get("authorized") is not False
            or stored.get("attempt_identity") != self.attempt_identity
        ):
            raise ValueError("Prepared classification candidate changed")
        return stored

    def preflight(self) -> dict:
        """Re-verify every frozen seam before any possible authorization."""
        stored = self.candidate
        if stored.get("native_launches") != 0 or stored.get("requests_sent") != 0:
            raise PermissionError("Candidate cannot allocate a launch itself")
        verify_freeze(stored["frozen_source"])
        for name, entry in stored["retained_reference"].items():
            path = SEED17_RUN / name
            if not path.is_file() or sha256(path) != entry["sha256"]:
                raise ValueError(f"Retained reference changed or missing: {name}")
        seams = validate_staging_seams()
        if seams["classification_package_digest"] != stored["package"]["digest"]:
            raise ValueError("Staged package composition drifted")
        plan = request_plan()
        if [hashlib.sha256(payload).hexdigest() for payload in plan] != [
            item["request_payload_sha256"] for item in stored["plan"]["pages"]
        ]:
            raise ValueError("Classification request plan drifted")
        if (
            len(plan) != stored["plan"]["pages_count"]
            or len(stored["plan"]["pages"]) != stored["plan"]["pages_count"]
        ):
            raise ValueError("Prepared page count contradicts the plan")
        facts = retained_facts()
        if (
            facts.region.x,
            facts.region.y,
            facts.region.width,
            facts.region.height,
        ) != tuple(stored["plan"]["region"]):
            raise ValueError("Prepared classification region drifted")
        return stored


def prepare(directory: Path | None = None) -> PreparedCapture:
    """Materialize the PENDING_AUTHORIZATION candidate (no launch, no claim)."""
    facts = retained_facts()
    welcome = retained_welcome()
    for key in WELCOME_IDENTITY_KEYS:
        if key not in welcome:
            raise ValueError(f"retained welcome record lacks {key!r}")
    package = classification_package_bytes()
    package_digest = classification_package_digest(package)
    seams = validate_staging_seams()
    if seams["classification_package_digest"] != package_digest:
        raise ValueError("seam digest contradicts the staged package")
    plan = request_plan()
    retained_reference = {
        name: {"sha256": sha256(SEED17_RUN / name)} for name in RETAINED_REFERENCES
    }
    frozen = classification_source_freeze()
    identity_payload = {
        "kind": CAPTURE_KIND,
        "classification_package_digest": package_digest,
        "v1_terrain_composition_sha256": seams["v1_terrain_composition_sha256"],
        "retained_reference": retained_reference,
        "region": [facts.region.x, facts.region.y, facts.region.width, facts.region.height],
        "tiles": len(facts.tiles),
        "request_payload_sha256": [hashlib.sha256(payload).hexdigest() for payload in plan],
        "schema_version": CLASSIFICATION_SCHEMA_VERSION,
        "seed": welcome.get("seed"),
    }
    attempt_identity = hashlib.sha256(
        json.dumps(identity_payload, sort_keys=True).encode()
    ).hexdigest()
    directory = directory or (ARTIFACT_ROOT / f"classification-seed17-{attempt_identity[:8]}")
    candidate_path = directory / "CANDIDATE.json"
    if candidate_path.is_file():
        stored = json.loads(candidate_path.read_bytes())
        if stored.get("kind") != CAPTURE_KIND or stored.get("attempt_identity") not in (
            None,
            attempt_identity,
        ):
            raise ValueError("Prepared classification directory belongs to another attempt")
        if all(
            (directory / name).is_file()
            for name in (
                "classification-requests.json",
                "receipts-required.json",
                "cleanup.json",
                "AUTHORIZATION_REQUIRED.json",
            )
        ):
            return PreparedCapture(
                directory=directory,
                attempt_identity=attempt_identity,
                package_digest=stored["package"]["digest"],
                pages=stored["plan"]["pages_count"],
                tiles=stored["plan"]["tiles"],
            )
    directory.mkdir(parents=True, exist_ok=True)
    config_path = str(directory / "isolated" / "openttd-15.3-staged" / "openttd.cfg")
    candidate = {
        "schema_version": 1,
        "kind": CAPTURE_KIND,
        "attempt_identity": attempt_identity,
        "state": STATE,
        "authorized": False,
        "maximum_launches": 1,
        "native_launches": 0,
        "requests_sent": 0,
        "authorization": (
            "requires ONE fresh operator authorization after preflight; offline preparation "
            "consumed no claim and the retained Seed 17 attempt remains consumed and untouched"
        ),
        "schema_version_wire": CLASSIFICATION_SCHEMA_VERSION,
        "package": {
            "files": {
                name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
                for name, data in sorted(classification_package_bytes().items())
            },
            "digest": package_digest,
        },
        "v1_compositions": {
            "terrain_composition_sha256": seams["v1_terrain_composition_sha256"],
            "statement": (
                "v1 terrain capture package identity is frozen; this candidate adds "
                "a new additive composition only"
            ),
        },
        "plan": {
            "request_id": CLASSIFICATION_REQUEST_ID,
            "region": [
                facts.region.x,
                facts.region.y,
                facts.region.width,
                facts.region.height,
            ],
            "bands": 2,
            "pages_count": len(plan),
            "tiles": len(facts.tiles),
            "pages": [
                {
                    "index": index,
                    "request_bytes_limit": 159,
                    "request_payload_sha256": hashlib.sha256(payload).hexdigest(),
                }
                for index, payload in enumerate(plan)
            ],
        },
        "budgets": {
            "pages_limit": CLASSIFICATION_PAGE_LIMIT,
            "total_response_bytes_limit": CLASSIFICATION_TOTAL_RESPONSE_BYTES_LIMIT,
            "requests": len(plan),
            "gsadmin_bytes_per_page": GSADMIN_BYTES,
            "observation_seconds": OBSERVATION_SECONDS,
            "launches": 1,
            "connections": 1,
            "retries": 0,
        },
        "world_identity_requirements": {
            "welcome_keys": list(WELCOME_IDENTITY_KEYS),
            "retained_welcome": {
                key: welcome[key] for key in WELCOME_IDENTITY_KEYS if key in welcome
            },
            "correspondence_rule": (
                "same-seed recipes are not the same world: a fresh launch echoes the "
                "retained welcome keys and every classified tile must still agree with "
                "the retained TileFact projection (height, slope, industry, projected "
                "flags) before any observation is fused"
            ),
        },
        "receipts_required": [
            "one correlation receipt per page binding request bytes to response bytes",
            "one per-page envelope inside the 508-byte response budget",
            "complete in-order page set with no gaps, duplicates or reorderings",
            "complete census bound against the retained TileFact projection "
            "(coherence with every shared predicate bit)",
            "machine-readable completeness summary plus feasibility assessment record",
        ],
        "retained_reference": retained_reference,
        "frozen_source": frozen,
        "launch_command_template": launch_command_template(config_path),
        "cleanup": list(cleanup_procedure()),
        "connection_requirements": (
            "dedicated server (-D) on freshly reserved localhost endpoints",
            "one AdminPort connection",
            "GameScript bridge exchange only through the staged additive package",
            "no interactive GUI required",
        ),
    }
    write_json(directory / "CANDIDATE.json", candidate)
    requests_payload = {
        "request_id": CLASSIFICATION_REQUEST_ID,
        "pages": [
            {"index": index, "request": payload.decode()} for index, payload in enumerate(plan)
        ],
    }
    write_json(directory / "classification-requests.json", requests_payload)
    write_json(
        directory / "receipts-required.json",
        {
            "pages": len(plan),
            "response_bytes_limit": GSADMIN_BYTES,
            "statements": candidate["receipts_required"],
        },
    )
    write_json(directory / "cleanup.json", {"steps": list(cleanup_procedure())})
    write_json(
        directory / "AUTHORIZATION_REQUIRED.json",
        {
            "state": STATE,
            "statement": candidate["authorization"],
            "launch_command_template": candidate["launch_command_template"],
        },
    )
    return PreparedCapture(
        directory=directory,
        attempt_identity=attempt_identity,
        package_digest=package_digest,
        pages=len(plan),
        tiles=len(facts.tiles),
    )
