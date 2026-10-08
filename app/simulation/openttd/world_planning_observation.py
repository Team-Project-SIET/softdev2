"""Immutable PRE-PLANNING composition; no queries, candidate generation or execution.

A trusted issuer owns real-proof acceptance. This model validates the immutable
semantic qualification witness, not cleanup/offline acceptance or a save file.
"""

import hashlib
import json
from dataclasses import dataclass, replace

from app.simulation.openttd.observation_protocol import BridgeProtocolError
from app.simulation.openttd.production_observation import (
    IndustryProductionObservation,
    ProductionWindowQualification,
    production_pairs,
)
from app.simulation.openttd.qualification_stability import QualifiedProductionVerification
from app.simulation.openttd.qualified_production import QualifiedProductionResult
from app.simulation.openttd.structural_world import StructuralWorldObservation


@dataclass(frozen=True)
class WorldPlanningObservation:
    structural: StructuralWorldObservation
    qualification: QualifiedProductionResult

    def __post_init__(self) -> None:
        if not isinstance(self.structural, StructuralWorldObservation) or not isinstance(
            self.qualification, QualifiedProductionResult
        ):
            raise BridgeProtocolError("typed structural observation and qualification required")
        if not isinstance(self.qualification.verification, QualifiedProductionVerification):
            raise BridgeProtocolError("typed qualification verification required")
        production = self.production
        if not isinstance(production, IndustryProductionObservation) or not isinstance(
            production.qualification, ProductionWindowQualification
        ):
            raise BridgeProtocolError("typed production and qualification metadata required")
        if not self.structural.complete or not production.complete:
            raise BridgeProtocolError("complete structural and production observations required")
        if not production.qualified_for_planning:
            raise BridgeProtocolError("qualified production required")
        replace(self.structural)
        replace(self.qualification)
        if (
            self.structural is not self.qualification.verification.stability.final
            or production.source is not self.structural
            or production.source_structural_world_digest != self.structural.structural_world_digest
        ):
            raise BridgeProtocolError("exact final structural source required")
        self.context.require_same_run(production.context)
        if tuple(r.pair for r in production.records) != production_pairs(self.structural):
            raise BridgeProtocolError("exact produced-target coverage required")
        # Reuse native boundary validation; economy time is not a planner calendar.
        replace(self.qualified_month_identity)

    @property
    def production(self) -> IndustryProductionObservation:
        return self.qualification.production

    @property
    def qualified_month_identity(self):
        return self.qualification.qualified_month_identity

    @property
    def context(self):
        return self.structural.inventory.context

    @property
    def complete(self) -> bool:
        return True  # No partial observation is published by this constructor.

    def to_bytes(self) -> bytes:
        month = self.qualification.qualified_month
        return json.dumps(
            dict(
                schema="world-planning-observation-v1",
                structural_world_digest=self.structural.structural_world_digest,
                production_digest=self.production.production_digest,
                qualified_month=dict(
                    economy_year=month.year,
                    economy_month=month.month,
                    start_date=month.start_date,
                    end_date=month.end_date,
                ),
                relevant_industry_lifetimes=[
                    dict(industry_id=r.industry_id, construction_date=r.construction_date)
                    for r in self.qualification.verification.stability.final_lifetimes
                ],
            ),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @property
    def composition_digest(self) -> str:
        return hashlib.sha256(self.to_bytes()).hexdigest()
