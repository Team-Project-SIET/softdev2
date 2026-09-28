"""Planning schema v1. No runtime, database, or legacy logistics dependencies."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, model_validator


def _decimal(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, Decimal)):
        raise ValueError("decimal values must be decimal strings")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal value") from exc
    if not result.is_finite():
        raise ValueError("decimal value must be finite")
    return result


Amount = Annotated[Decimal, BeforeValidator(_decimal)]
NonNegativeAmount = Annotated[Amount, Field(ge=0)]
PositiveAmount = Annotated[Amount, Field(gt=0)]


def _safe_identifier(value: str) -> str:
    if ".." in value:
        raise ValueError("identifier cannot contain parent traversal")
    return value


Identifier = Annotated[
    str,
    Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"),
    AfterValidator(_safe_identifier),
]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0)]


class Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class Mode(StrEnum):
    ROAD = "road"
    RAIL = "rail"


class LocationKind(StrEnum):
    INDUSTRY_ORIGIN = "industry_origin"
    INDUSTRY_DESTINATION = "industry_destination"
    STATION_CANDIDATE = "station_candidate"
    DEPOT_CANDIDATE = "depot_candidate"
    SERVICE_WAYPOINT = "service_waypoint"


class StopRole(StrEnum):
    PICKUP = "pickup"
    DELIVERY = "delivery"
    DEPOT = "depot"
    SERVICE = "service"


class ConstructionKind(StrEnum):
    STATION = "station"
    DEPOT = "depot"
    SEGMENT = "segment"


class SourceReference(Contract):
    source_kind: Identifier
    source_id: Identifier
    source_version: Identifier | None = None
    source_digest: Digest | None = None

    @model_validator(mode="after")
    def has_version(self) -> SourceReference:
        if self.source_version is None and self.source_digest is None:
            raise ValueError("source reference needs version or digest")
        return self


class Tile(Contract):
    x: NonNegativeInt
    y: NonNegativeInt


class WorldReference(Contract):
    world_fingerprint: Digest
    kind: Literal["industry", "station"]
    world_id: NonNegativeInt


class PlanningLocation(Contract):
    location_id: Identifier
    tile: Tile
    kind: LocationKind
    permitted_modes: tuple[Mode, ...]
    footprint_width_tiles: PositiveInt | None = None
    footprint_height_tiles: PositiveInt | None = None
    orientation: Literal["north", "east", "south", "west"] | None = None
    platform_length_tiles: PositiveInt | None = None
    serves_location_id: Identifier | None = None
    facility_class: Identifier | None = None
    world_reference: WorldReference | None = None
    source: SourceReference | None = None


class CargoDemand(Contract):
    demand_id: Identifier
    cargo_type: Identifier
    origin_id: Identifier
    destination_id: Identifier
    quantity: PositiveInt
    unit: Literal["cargo_units"]
    earliest_day: NonNegativeInt
    latest_delivery_day: NonNegativeInt
    source: SourceReference
    priority: Literal["low", "normal", "high"] | None = None
    max_transit_days: PositiveInt | None = None


class VehicleDefinition(Contract):
    vehicle_type: Identifier
    capacity_cargo_units: NonNegativeInt
    purchase_cost_gbp: NonNegativeAmount
    running_cost_gbp_per_day: NonNegativeAmount
    speed_km_per_hour: PositiveAmount
    length_tiles: PositiveInt | None = None
    compatible_cargo_types: tuple[Identifier, ...]


class RoadFleetOption(Contract):
    option_id: Identifier
    mode: Literal[Mode.ROAD]
    vehicle: VehicleDefinition
    road_vehicle_class: Identifier
    depot_class: Identifier
    available_from_day: NonNegativeInt
    available_through_day: NonNegativeInt
    source: SourceReference


class RailFleetOption(Contract):
    option_id: Identifier
    mode: Literal[Mode.RAIL]
    locomotive: VehicleDefinition
    wagon_options: tuple[VehicleDefinition, ...] = Field(min_length=1)
    rail_type: Identifier
    max_train_length_tiles: PositiveInt
    available_from_day: NonNegativeInt
    available_through_day: NonNegativeInt
    source: SourceReference


FleetOption = Annotated[RoadFleetOption | RailFleetOption, Field(discriminator="mode")]


class InfrastructureCandidate(Contract):
    candidate_id: Identifier
    mode: Mode
    kind: ConstructionKind
    site_id: Identifier | None = None
    origin_id: Identifier | None = None
    destination_id: Identifier | None = None
    tiles: tuple[Tile, ...] = ()
    footprint_width_tiles: PositiveInt | None = None
    footprint_height_tiles: PositiveInt | None = None
    orientation: Literal["north", "east", "south", "west"] | None = None
    rail_type: Identifier | None = None
    estimated_build_cost_gbp: NonNegativeAmount
    source: SourceReference


class EconomicAssumptions(Contract):
    currency: Literal["GBP"]
    model_name: Identifier
    model_version: Identifier
    revenue_gbp_per_cargo_unit: NonNegativeAmount | None = None
    finance_cost_gbp_per_day: NonNegativeAmount | None = None
    undelivered_penalty_gbp_per_cargo_unit: NonNegativeAmount | None = None
    late_penalty_gbp_per_cargo_unit_day: NonNegativeAmount | None = None


class PlanningConstraints(Contract):
    budget_gbp: NonNegativeAmount | None = None
    permitted_modes: tuple[Mode, ...]
    max_train_length_tiles: PositiveInt | None = None


class ResolvedSite(Contract):
    """Independent prepared-world description of a scenario-local site."""

    location_id: Identifier
    tile: Tile
    kind: LocationKind
    permitted_modes: tuple[Mode, ...]
    serves_location_id: Identifier | None = None
    footprint_width_tiles: PositiveInt | None = None
    footprint_height_tiles: PositiveInt | None = None
    orientation: Literal["north", "east", "south", "west"] | None = None
    platform_length_tiles: PositiveInt | None = None
    facility_class: Identifier | None = None
    world_kind: Literal["industry", "station"] | None = None
    world_id: NonNegativeInt | None = None

    @model_validator(mode="after")
    def world_reference_is_complete(self) -> ResolvedSite:
        if (self.world_kind is None) != (self.world_id is None):
            raise ValueError("world kind and ID must appear together")
        return self


class PreparedWorldManifest(Contract):
    """Supplied world evidence; P02 checks its integrity, not its OpenTTD origin."""

    schema_version: Literal[1]
    source_digest: Digest
    openttd_version: Identifier
    base_set_name: Identifier
    base_set_version: Identifier
    width_tiles: PositiveInt
    height_tiles: PositiveInt
    seed: NonNegativeInt
    resolved_sites: tuple[ResolvedSite, ...]
    cargo_types: tuple[Identifier, ...]
    vehicle_types: tuple[Identifier, ...]
    buildable_tiles: tuple[Tile, ...]


class PlanningScenario(Contract):
    schema_version: Literal[1]
    scenario_id: Identifier
    scenario_version: Identifier
    world_fingerprint: Digest
    world_manifest: PreparedWorldManifest
    openttd_version: Identifier
    base_set_name: Identifier
    base_set_version: Identifier
    width_tiles: PositiveInt
    height_tiles: PositiveInt
    seed: NonNegativeInt
    start_date: date
    horizon_days: PositiveInt
    supported_modes: tuple[Mode, ...] = Field(min_length=1)
    locations: tuple[PlanningLocation, ...] = Field(min_length=1)
    cargo_demands: tuple[CargoDemand, ...] = Field(min_length=1)
    fleet_options: tuple[FleetOption, ...] = Field(min_length=1)
    infrastructure_candidates: tuple[InfrastructureCandidate, ...] = Field(min_length=1)
    economic_assumptions: EconomicAssumptions
    constraints: PlanningConstraints


class RouteStop(Contract):
    location_id: Identifier
    role: StopRole


class CargoAssignment(Contract):
    demand_id: Identifier
    quantity: PositiveInt
    unit: Literal["cargo_units"]


class RoutePlan(Contract):
    route_id: Identifier
    mode: Mode
    path_kind: Literal["station_to_station_intent"]
    origin_id: Identifier
    destination_id: Identifier
    stops: tuple[RouteStop, ...] = Field(min_length=3)
    cargo_assignments: tuple[CargoAssignment, ...] = Field(min_length=1)
    fleet_group_id: Identifier
    infrastructure_ids: tuple[Identifier, ...] = Field(min_length=1)
    source: SourceReference | None = None


class WagonComposition(Contract):
    wagon_type: Identifier
    count: PositiveInt


class RoadComposition(Contract):
    mode: Literal[Mode.ROAD]
    vehicle_type: Identifier


class RailComposition(Contract):
    mode: Literal[Mode.RAIL]
    locomotive_type: Identifier
    wagons: tuple[WagonComposition, ...] = Field(min_length=1)
    total_capacity_cargo_units: PositiveInt
    total_length_tiles: PositiveInt


Composition = Annotated[RoadComposition | RailComposition, Field(discriminator="mode")]


class FleetGroup(Contract):
    fleet_group_id: Identifier
    mode: Mode
    option_id: Identifier
    count: PositiveInt
    route_ids: tuple[Identifier, ...] = Field(min_length=1)
    demand_ids: tuple[Identifier, ...] = Field(min_length=1)
    start_day: NonNegativeInt
    order_mode: Literal["repeat_service"]
    planned_trips_per_vehicle: PositiveInt
    composition: Composition


class FleetPlan(Contract):
    groups: tuple[FleetGroup, ...] = Field(min_length=1)


class ConstructionAction(Contract):
    construction_id: Identifier
    candidate_id: Identifier
    mode: Mode
    kind: ConstructionKind
    depends_on: tuple[Identifier, ...] = ()
    route_ids: tuple[Identifier, ...] = Field(min_length=1)
    estimated_build_cost_gbp: NonNegativeAmount


class InfrastructurePlan(Contract):
    actions: tuple[ConstructionAction, ...] = Field(min_length=1)


class ValidationDeclaration(Contract):
    validator_version: Identifier
    supported_modes: tuple[Mode, ...] = Field(min_length=1)
    validated_world_fingerprint: Digest


class ExecutionPlan(Contract):
    schema_version: Literal[1]
    plan_id: Identifier
    scenario_id: Identifier
    scenario_version: Identifier
    world_fingerprint: Digest
    planner_name: Identifier
    planner_version: Identifier
    strategy_identifier: Identifier
    strategy_version: Identifier
    planner_inputs_digest: Digest
    planner_random_seed: NonNegativeInt | None = None
    routes: tuple[RoutePlan, ...] = Field(min_length=1)
    fleet: FleetPlan
    infrastructure: InfrastructurePlan
    validation: ValidationDeclaration


class EstimatedPlanMetrics(Contract):
    schema_version: Literal[1]
    plan_hash: Digest
    estimator_name: Identifier
    estimator_version: Identifier
    assumptions_digest: Digest
    horizon_days: PositiveInt
    currency: Literal["GBP"]
    predicted_delivered_cargo_units: NonNegativeInt | None = None
    revenue_gbp: NonNegativeAmount | None = None
    infrastructure_spend_gbp: NonNegativeAmount | None = None
    vehicle_purchase_cost_gbp: NonNegativeAmount | None = None
    vehicle_running_cost_gbp: NonNegativeAmount | None = None
    finance_cost_gbp: NonNegativeAmount | None = None
    penalties_gbp: NonNegativeAmount | None = None
    estimated_net_profit_gbp: Amount | None = None
