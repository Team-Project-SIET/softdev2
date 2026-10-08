"""Pure controlled correspondence. Byte identity never confers runtime authority."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from app.planning.canonical import world_manifest_hash
from app.planning.domain import Contract, Digest, PreparedWorldManifest
from app.simulation.openttd.supplemental_planning_facts import PlanningFactError
from app.simulation.openttd.world_planning_observation import WorldPlanningObservation


class SourceTrust(StrEnum):
    CONTROLLED_FIXTURE = "CONTROLLED_FIXTURE"
    SOURCE_BYTES_VERIFIED = "SOURCE_BYTES_VERIFIED"
    REAL_RUNTIME_CORRESPONDENCE_PROVEN = "REAL_RUNTIME_CORRESPONDENCE_PROVEN"


class ControlledSourceLinks(Contract):
    """Explicitly simulated, not independently established native receipts."""

    original_save_digest: Digest
    loaded_source_digest: Digest | None
    runtime_digest: Digest
    configuration_digest: Digest
    bridge_digest: Digest
    world_id: str
    world_observation_digest: Digest
    final_structural_digest: Digest
    qualified_production_digest: Digest
    post_qualification_save_digest: Digest | None
    # This describes evidence kind, never real-proof authority.
    evidence_kind: Literal["controlled-simulation", "missing"]

    def require_world(self, world: WorldPlanningObservation) -> None:
        c = world.context
        if (
            self.runtime_digest != c.world.runtime_identity.sha256
            or self.configuration_digest != c.configuration_digest
            or self.bridge_digest != c.bridge.sha256
            or self.world_id != c.world.world_id
            or self.world_observation_digest != world.composition_digest
            or self.final_structural_digest != world.structural.structural_world_digest
            or self.qualified_production_digest != world.production.production_digest
        ):
            raise PlanningFactError("source correspondence runtime/observation mismatch")
        if (
            self.loaded_source_digest is not None
            and self.loaded_source_digest != self.original_save_digest
        ):
            raise PlanningFactError("loaded source bytes identity mismatch")
        if self.evidence_kind == "missing" and (
            self.loaded_source_digest is not None or self.post_qualification_save_digest is not None
        ):
            raise PlanningFactError("missing evidence cannot assert save correspondence")


@dataclass(frozen=True)
class PreparedSourceCorrespondence:
    """Composes existing manifest identity with separately identified saved states."""

    world: WorldPlanningObservation
    manifest: PreparedWorldManifest
    links: ControlledSourceLinks

    def __post_init__(self) -> None:
        if (
            not isinstance(self.world, WorldPlanningObservation)
            or not isinstance(self.manifest, PreparedWorldManifest)
            or not isinstance(self.links, ControlledSourceLinks)
        ):
            raise PlanningFactError("typed observation, manifest and source links required")
        ControlledSourceLinks.model_validate_json(self.links.model_dump_json())
        PreparedWorldManifest.model_validate_json(self.manifest.model_dump_json())
        self.links.require_world(self.world)
        # A manifest may refer to original bytes, or separately identified final bytes.
        if self.manifest.source_digest not in (
            self.links.original_save_digest,
            self.links.post_qualification_save_digest,
        ):
            raise PlanningFactError("prepared manifest save source mismatch")
        if (self.manifest.width_tiles, self.manifest.height_tiles) != (
            self.world.context.world.map_width,
            self.world.context.world.map_height,
        ):
            raise PlanningFactError("prepared manifest map dimensions mismatch")
        if self.manifest.openttd_version != self.world.context.world.runtime_identity.version:
            raise PlanningFactError("prepared manifest runtime version mismatch")

    @property
    def world_fingerprint(self) -> str:
        return world_manifest_hash(self.manifest)

    @property
    def post_qualification_status(self) -> str:
        return (
            "UNPROVEN"
            if self.links.post_qualification_save_digest is None
            else "CONTROLLED_SIMULATED"
        )

    @property
    def trust(self) -> SourceTrust:
        return SourceTrust.CONTROLLED_FIXTURE

    def require_real_executable_source(self) -> None:
        # No authoritative native save/load/capture evidence issuer exists yet.
        raise PlanningFactError(
            "real executable source blocked: trusted post-qualification correspondence unproven"
        )
