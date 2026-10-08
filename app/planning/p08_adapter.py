"""Controlled 15.3 fact mapping. No geometry, solver, native reads or execution."""

from calendar import monthrange
from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum
from hashlib import sha256

from app.planning.canonical import canonical_bytes
from app.planning.domain import Contract, NonNegativeAmount, PreparedWorldManifest
from app.simulation.openttd.planning_fact_input import ValidatedPlanningFactInput
from app.simulation.openttd.prepared_source_correspondence import SourceTrust
from app.simulation.openttd.supplemental_planning_facts import SupplementalPlanningFacts


class RoadOutcome(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    UNQUALIFIED_OBSERVATION = "UNQUALIFIED_OBSERVATION"
    SOURCE_MISMATCH = "SOURCE_MISMATCH"
    MISSING_PROVENANCE = "MISSING_PROVENANCE"
    INVALID_SOURCE_CORRESPONDENCE = "INVALID_SOURCE_CORRESPONDENCE"
    NO_ELIGIBLE_BENCHMARK = "NO_ELIGIBLE_BENCHMARK"
    ZERO_POSITIVE_SUPPLY = "ZERO_POSITIVE_SUPPLY"
    INSUFFICIENT_COVERAGE = "INSUFFICIENT_COVERAGE"
    MISSING_CATCHMENT = "MISSING_CATCHMENT"
    NO_STATION_PLACEMENT = "NO_STATION_PLACEMENT"
    NO_DEPOT_PLACEMENT = "NO_DEPOT_PLACEMENT"
    NO_BOUNDED_CORRIDOR = "NO_BOUNDED_CORRIDOR"
    SEARCH_LIMIT_EXCEEDED = "SEARCH_LIMIT_EXCEEDED"
    INVALID_ENGINE_COMPATIBILITY = "INVALID_ENGINE_COMPATIBILITY"
    CAPACITY_INFEASIBLE = "CAPACITY_INFEASIBLE"
    COST_INFEASIBLE = "COST_INFEASIBLE"
    CONFLICTING_IDENTITIES = "CONFLICTING_IDENTITIES"


class AdapterError(ValueError):
    """Admission failures retain the authoritative validator's cause and message."""

    def __init__(self, detail: str) -> None:
        self.code = RoadOutcome.INVALID_INPUT
        # Classify authoritative admission failures without reimplementing their gates.
        if any(s in detail for s in ("qualified", "qualification", "complete")):
            self.code = RoadOutcome.UNQUALIFIED_OBSERVATION
        if any(s in detail for s in ("source", "identity mismatch", "same run", "structural")):
            self.code = RoadOutcome.SOURCE_MISMATCH
        if any(s in detail for s in ("provenance", "typed runtime", "context")):
            self.code = RoadOutcome.MISSING_PROVENANCE
        if any(s in detail for s in ("correspondence", "manifest", "save")):
            self.code = RoadOutcome.INVALID_SOURCE_CORRESPONDENCE
        super().__init__(detail)


class MonthlyBatchPolicy(Contract):
    """Historical supply batch, one assumed load per vehicle; no measured demand."""

    start_date: date  # Configured benchmark calendar, never inferred from economy ticks.
    budget_gbp: NonNegativeAmount | None = None

    @property
    def horizon_days(self) -> int:
        return monthrange(self.start_date.year, self.start_date.month)[1]

    @property
    def digest(self) -> str:
        return sha256(canonical_bytes(self)).hexdigest()


POLICY_VERSION = "qualified-month-batch-v1"
MAX_VEHICLES = 64
MAX_STATIONS_PER_ROLE = 4
MAX_STATION_PAIRS = MAX_STATIONS_PER_ROLE**2
MAX_PATH_EXPANSIONS = MAX_STATION_PAIRS * 256


@dataclass(frozen=True)
class QualifiedSupply:
    industry_id: int
    cargo_id: int
    quantity: int
    economy_year: int
    economy_month: int
    structural_digest: str


@dataclass(frozen=True)
class Industry:
    industry_id: int
    x: int
    y: int
    produces: tuple[int, ...]
    accepts: tuple[int, ...]


@dataclass(frozen=True)
class Cargo:
    cargo_id: int
    identifier: str
    freight: bool


@dataclass(frozen=True)
class RoadProvenance:
    world_observation_digest: str
    supplemental_digest: str
    input_manifest_fingerprint: str
    policy_digest: str
    policy_version: str = POLICY_VERSION
    trust: SourceTrust = SourceTrust.CONTROLLED_FIXTURE

    @property
    def digest(self) -> str:
        return sha256(
            "|".join(
                (
                    self.world_observation_digest,
                    self.supplemental_digest,
                    self.input_manifest_fingerprint,
                    self.policy_digest,
                    self.policy_version,
                    self.trust.value,
                )
            ).encode()
        ).hexdigest()


@dataclass(frozen=True)
class BoundedRoadInput:
    """Adapter-issued mapping; facts keep their original numeric meanings and units."""

    admitted: ValidatedPlanningFactInput
    policy: MonthlyBatchPolicy
    industries: tuple[Industry, ...]
    cargos: tuple[Cargo, ...]
    supplies: tuple[QualifiedSupply, ...]
    provenance: RoadProvenance

    @property
    def facts(self) -> SupplementalPlanningFacts:
        return self.admitted.supplemental

    @property
    def manifest(self) -> PreparedWorldManifest:
        return self.admitted.correspondence.manifest


def adapt_planning_facts(
    value: ValidatedPlanningFactInput, policy: MonthlyBatchPolicy
) -> BoundedRoadInput:
    """Re-enter the authoritative admission seam, including unchecked-object rejection."""
    try:
        if not isinstance(value, ValidatedPlanningFactInput) or not isinstance(
            policy, MonthlyBatchPolicy
        ):
            raise ValueError("typed validated input and benchmark policy required")
        replace(value)
        MonthlyBatchPolicy.model_validate_json(policy.model_dump_json())
        if policy.start_date.day != 1:
            raise ValueError("benchmark must start on the first day of its configured month")
    except ValueError as exc:
        raise AdapterError(str(exc)) from exc
    capabilities = {
        c.industry_id: c for c in value.world.structural.capability.observation.capabilities
    }
    industries = tuple(
        Industry(
            r.id,
            r.x,
            r.y,
            tuple(sorted(capabilities[r.id].produces)),
            tuple(sorted(capabilities[r.id].accepts)),
        )
        for r in sorted(value.world.structural.inventory.observation.records, key=lambda r: r.id)
    )
    cargos = tuple(
        Cargo(r.cargo_id, f"cargo-{r.cargo_label}", r.is_freight)
        for r in sorted(
            value.world.structural.catalog.observation.records, key=lambda r: r.cargo_id
        )
    )
    if len({c.identifier for c in cargos}) != len(cargos):
        raise AdapterError("conflicting native cargo labels")
    month = value.world.qualified_month_identity
    supplies = tuple(
        QualifiedSupply(
            r.industry_id,
            r.cargo_id,
            r.last_month_produced,
            month.economy_year,
            month.economy_month,
            value.world.structural.structural_world_digest,
        )
        for r in sorted(value.world.production.records, key=lambda r: (r.industry_id, r.cargo_id))
    )
    return BoundedRoadInput(
        value,
        policy,
        industries,
        cargos,
        supplies,
        RoadProvenance(
            value.world.composition_digest,
            value.supplemental.semantic_digest,
            value.correspondence.world_fingerprint,
            policy.digest,
            trust=value.correspondence.trust,
        ),
    )
