"""Strict P08 extraction/preparation contracts, independent of runtime and persistence."""

from datetime import date
from typing import Literal

from pydantic import Field

from app.planning.domain import (
    Contract,
    Digest,
    Identifier,
    NonNegativeAmount,
    NonNegativeInt,
    PlanningScenario,
    PositiveInt,
    PreparedWorldManifest,
)
from app.planning.execution import ExecutionBindings


class SupportedWorldProfile(Contract):
    openttd_version: str = "13.4"
    base_set_name: str = "OpenGFX"
    base_set_version: Identifier = "7.1"
    landscape: str = "temperate"
    newgrfs: tuple[Identifier, ...] = ()
    competing_active_companies: NonNegativeInt = 0
    preparation_compatible: bool = True
    road_type: NonNegativeInt = 0
    catchment_radius: NonNegativeInt = 3
    acceptance_threshold: PositiveInt = 8


class PreparationLimits(Contract):
    version: Literal["p08-limits-v1"] = "p08-limits-v1"
    map_tiles: PositiveInt = Field(default=65536, le=65536)
    industries: PositiveInt = Field(default=32, le=32)
    relationships: PositiveInt = Field(default=16, le=16)
    demands: PositiveInt = Field(default=1, le=1)
    stations_per_role: PositiveInt = Field(default=4, le=4)
    depots: PositiveInt = Field(default=1, le=1)
    corridors_per_pair: PositiveInt = Field(default=2, le=2)
    fleet_options: PositiveInt = Field(default=32, le=32)
    infrastructure_candidates: PositiveInt = Field(default=64, le=64)
    corridor_length: PositiveInt = Field(default=4096, le=4096)
    search_states_per_pair: PositiveInt = Field(default=250000, le=250000)
    aggregate_expansions: PositiveInt = Field(default=2000000, le=2000000)
    scenario_bytes: PositiveInt = Field(default=4194304, le=4194304)


class PreparationRequest(Contract):
    schema_version: Literal[1] = 1
    scenario_id: Identifier
    horizon_days: PositiveInt
    expected_source_save_digest: Digest
    policy_version: Literal["p08-v1"] = "p08-v1"
    limits: PreparationLimits = PreparationLimits()


class TileCargoFact(Contract):
    cargo_id: NonNegativeInt
    production: NonNegativeInt
    acceptance_eighths: NonNegativeInt


class ExtractedTile(Contract):
    tile_index: NonNegativeInt
    x: NonNegativeInt
    y: NonNegativeInt
    height: NonNegativeInt
    slope: NonNegativeInt
    land_class: Literal["land", "water", "coast"]
    occupancy: Literal["vacant", "industry", "trees", "other"]
    transport_occupied: bool
    industry_id: NonNegativeInt | None
    build_eligible: bool
    clearing_required: bool
    cargo_facts: tuple[TileCargoFact, ...] = ()


class IndustryCargoFact(Contract):
    cargo_id: NonNegativeInt
    last_month_production: NonNegativeInt
    accepts: bool


class ExtractedIndustry(Contract):
    industry_id: NonNegativeInt
    name: str = Field(min_length=1, max_length=120)
    anchor_tile: NonNegativeInt
    footprint: tuple[NonNegativeInt, ...] = Field(min_length=1)
    cargos: tuple[IndustryCargoFact, ...]


class ExtractedCargo(Contract):
    cargo_id: NonNegativeInt
    label: Identifier
    name: str = Field(min_length=1, max_length=120)
    freight: bool


class ExtractedRoadEngine(Contract):
    engine_id: NonNegativeInt
    name: str = Field(min_length=1, max_length=120)
    default_cargo_id: NonNegativeInt
    freight: bool
    road_type: NonNegativeInt
    depot_class: Identifier
    immediately_buildable: bool
    articulated: bool
    refit_required: bool
    default_capacity: NonNegativeInt
    purchase_cost_gbp: NonNegativeAmount
    running_cost_gbp_per_year: NonNegativeAmount
    native_speed_units: PositiveInt


class ExtractedWorldSnapshot(Contract):
    schema_version: Literal[1]
    profile: SupportedWorldProfile
    width_tiles: PositiveInt
    height_tiles: PositiveInt
    seed: NonNegativeInt
    preparation_date: date
    company_id: NonNegativeInt
    source_save_digest: Digest
    prepared_save_digest: Digest
    policy_version: Literal["p08-v1"]
    complete: bool
    tiles: tuple[ExtractedTile, ...]
    industries: tuple[ExtractedIndustry, ...]
    cargos: tuple[ExtractedCargo, ...]
    engines: tuple[ExtractedRoadEngine, ...]
    road_build_cost_gbp: NonNegativeAmount
    station_build_cost_gbp: NonNegativeAmount
    depot_build_cost_gbp: NonNegativeAmount


class StationSamplingReport(Contract):
    industry_id: NonNegativeInt
    role: Literal["pickup", "delivery"]
    eligible_count: NonNegativeInt
    selected_tiles: tuple[NonNegativeInt, ...]


class CandidateGenerationReport(Contract):
    policy_version: Literal["p08-v1"] = "p08-v1"
    cost_model: Literal["native-flat-road-v1"] = "native-flat-road-v1"
    demand_policy: Literal["native-origin-cargo-destination-order-v1"] = (
        "native-origin-cargo-destination-order-v1"
    )
    station_policy: Literal["compass-nearest-v1"] = "compass-nearest-v1"
    depot_policy: Literal["front-connectivity-distance-v1"] = "front-connectivity-distance-v1"
    relationships_examined: NonNegativeInt
    station_sampling: tuple[StationSamplingReport, ...]
    depot_tile: NonNegativeInt
    depot_front: NonNegativeInt
    search_expansions: NonNegativeInt
    corridor_count: NonNegativeInt


class PreparationProvenance(Contract):
    schema_version: Literal[1] = 1
    policy_version: Literal["p08-v1"] = "p08-v1"
    request_hash: Digest
    probe_version: Literal["p08-probe-v1"] = "p08-probe-v1"
    probe_package_hash: Digest
    source_save_digest: Digest
    prepared_save_digest: Digest
    snapshot_hash: Digest
    candidate_report_hash: Digest
    manifest_hash: Digest
    scenario_hash: Digest
    bindings_hash: Digest


class PreparationBundle(Contract):
    request: PreparationRequest
    snapshot: ExtractedWorldSnapshot
    report: CandidateGenerationReport
    manifest: PreparedWorldManifest
    scenario: PlanningScenario
    bindings: ExecutionBindings
    provenance: PreparationProvenance
    provenance_hash: Digest
