"""Strict bounded import of owned artifacts; never a native-proof authority issuer."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.planning.domain import Contract, Digest, PreparedWorldManifest
from app.simulation.openttd.prepared_source_correspondence import (
    ControlledSourceLinks,
    PreparedSourceCorrespondence,
    SourceTrust,
)
from app.simulation.openttd.supplemental_planning_facts import (
    PlanningFactError,
    SupplementalPlanningFacts,
)
from app.simulation.openttd.world_planning_observation import WorldPlanningObservation

MAX_ARTIFACT_BYTES = 256 * 1024  # 256 tile + 512 coverage + 32 engine records, compact JSON.


class PlanningFactArtifact(Contract):
    schema_version: Literal[1]
    source_class: Literal["CONTROLLED_FIXTURE", "SOURCE_BYTES_VERIFIED"]
    facts_digest: Digest
    facts: SupplementalPlanningFacts


@dataclass(frozen=True)
class ImportedPlanningFacts:
    artifact: PlanningFactArtifact
    input_bytes_digest: str

    @property
    def trust(self) -> SourceTrust:
        # We hash bytes ourselves; runtime correspondence is never inferred from label.
        return (
            SourceTrust.SOURCE_BYTES_VERIFIED
            if self.artifact.source_class == "SOURCE_BYTES_VERIFIED"
            else SourceTrust.CONTROLLED_FIXTURE
        )


def _owned_bytes(root: Path, relative: str) -> bytes:
    path = Path(relative)
    if (
        not relative
        or path.is_absolute()
        or any(p in (".", "..") for p in relative.split("/"))
        or "\\" in relative
    ):
        raise PlanningFactError("unsafe artifact path")
    # Traverse directory descriptors with NOFOLLOW: reject symlinks, including parents.
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        owned = os.open(path.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            st = os.fstat(owned)
            if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_ARTIFACT_BYTES:
                raise PlanningFactError("artifact must be a bounded regular file")
            chunks = bytearray()
            while len(chunks) <= MAX_ARTIFACT_BYTES:
                chunk = os.read(owned, min(65536, MAX_ARTIFACT_BYTES + 1 - len(chunks)))
                if not chunk:
                    break
                chunks.extend(chunk)
            if len(chunks) > MAX_ARTIFACT_BYTES:
                raise PlanningFactError("artifact exceeds size limit")
            return bytes(chunks)
        finally:
            os.close(owned)
    finally:
        os.close(fd)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise PlanningFactError("duplicate JSON field")
        result[key] = value
    return result


def import_planning_facts(
    root: Path, relative: str, *, expected_bytes_digest: str, world: WorldPlanningObservation
) -> ImportedPlanningFacts:
    """Caller supplies accepted exact bytes and admitted WPO; source untouched."""
    try:
        raw = _owned_bytes(root, relative)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != expected_bytes_digest:
            raise PlanningFactError("artifact bytes digest mismatch")
        json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=lambda _: (_ for _ in ()).throw(
                PlanningFactError("nonfinite JSON value")
            ),
        )
        artifact = PlanningFactArtifact.model_validate_json(raw)
        if artifact.facts.semantic_digest != artifact.facts_digest:
            raise PlanningFactError("artifact semantic digest mismatch")
        if artifact.facts.source.world_observation_digest != world.composition_digest:
            raise PlanningFactError("unexpected artifact world identity")
        artifact.facts.require_world(world)
        return ImportedPlanningFacts(artifact, digest)
    except (OSError, ValueError, RecursionError) as exc:
        raise PlanningFactError(f"artifact rejected: {exc}") from exc


@dataclass(frozen=True)
class ImportedPreparedSource:
    correspondence: PreparedSourceCorrespondence
    original_bytes_digest: str
    post_qualification_bytes_digest: str | None

    @property
    def trust(self) -> SourceTrust:
        return SourceTrust.SOURCE_BYTES_VERIFIED


def import_prepared_source(
    root: Path,
    original_relative: str,
    *,
    world: WorldPlanningObservation,
    manifest: PreparedWorldManifest,
    links: ControlledSourceLinks,
    post_qualification_relative: str | None = None,
) -> ImportedPreparedSource:
    """Hashes bounded controlled save fixtures, not save parsing or native loading."""
    try:
        original = hashlib.sha256(_owned_bytes(root, original_relative)).hexdigest()
        if original != links.original_save_digest:
            raise PlanningFactError("original prepared save bytes digest mismatch")
        final = None
        if post_qualification_relative is not None:
            final = hashlib.sha256(_owned_bytes(root, post_qualification_relative)).hexdigest()
            if final != links.post_qualification_save_digest:
                raise PlanningFactError("post-qualification save bytes digest mismatch")
        elif links.post_qualification_save_digest is not None:
            raise PlanningFactError("declared final save bytes missing from import")
        return ImportedPreparedSource(
            PreparedSourceCorrespondence(world, manifest, links), original, final
        )
    except (OSError, ValueError) as exc:
        raise PlanningFactError(f"prepared source rejected: {exc}") from exc
