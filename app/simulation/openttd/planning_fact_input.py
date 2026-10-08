"""Validated offline input composition; no candidate generation or execution."""

from dataclasses import dataclass, replace

from app.simulation.openttd.prepared_source_correspondence import PreparedSourceCorrespondence
from app.simulation.openttd.supplemental_planning_facts import (
    PlanningFactError,
    SupplementalPlanningFacts,
)
from app.simulation.openttd.world_planning_observation import WorldPlanningObservation


@dataclass(frozen=True)
class ValidatedPlanningFactInput:
    world: WorldPlanningObservation
    supplemental: SupplementalPlanningFacts
    correspondence: PreparedSourceCorrespondence

    def __post_init__(self) -> None:
        if (
            not isinstance(self.world, WorldPlanningObservation)
            or not isinstance(self.supplemental, SupplementalPlanningFacts)
            or not isinstance(self.correspondence, PreparedSourceCorrespondence)
        ):
            raise PlanningFactError("typed planning fact composition required")
        replace(self.world)
        # Revalidate even inputs created using Pydantic's unchecked construction seam.
        SupplementalPlanningFacts.model_validate_json(self.supplemental.to_bytes()).require_world(
            self.world
        )
        replace(self.correspondence)
        if self.correspondence.manifest.seed != self.supplemental.settings.generation_seed:
            raise PlanningFactError("prepared manifest/settings seed mismatch")
        self.world.context.require_same_run(self.correspondence.world.context)
        if self.correspondence.world.composition_digest != self.world.composition_digest:
            raise PlanningFactError("correspondence belongs to another observation")

    def require_real_executable_source(self) -> None:
        self.correspondence.require_real_executable_source()

    def require_road_service_facts(self, industry_id: int, acceptor_id: int, cargo_id: int) -> None:
        """Validate an explicit benchmark relationship; never select or generate it."""
        if any(type(i) is not int for i in (industry_id, acceptor_id, cargo_id)):
            raise PlanningFactError("native typed integer references required")
        if industry_id == acceptor_id:
            raise PlanningFactError("minimum benchmark needs distinct supply and acceptor")
        records = self.world.production.records
        if not any(
            r.industry_id == industry_id and r.cargo_id == cargo_id and r.last_month_produced > 0
            for r in records
        ):
            raise PlanningFactError("no positive qualified supply for requested benchmark")
        scopes = {(c.industry_id, c.cargo_id, c.role) for c in self.supplemental.coverage_scopes}
        if not {(industry_id, cargo_id, "pickup"), (acceptor_id, cargo_id, "delivery")} <= scopes:
            raise PlanningFactError("required pickup/delivery coverage unavailable")
        catalog = self.world.structural.catalog.observation.records
        if not any(c.cargo_id == cargo_id and c.is_freight for c in catalog):
            raise PlanningFactError("minimum benchmark requires freight cargo")
        if not any(
            e.public_available and e.default_cargo_id == cargo_id for e in self.supplemental.engines
        ):
            raise PlanningFactError("required available default-cargo road engine unavailable")
