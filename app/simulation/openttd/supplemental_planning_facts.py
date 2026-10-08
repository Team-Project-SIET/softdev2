"""Pure, bounded road planning facts. Acceptance is not construction authority."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.planning.domain import Contract, Digest
from app.simulation.openttd.world_planning_observation import WorldPlanningObservation

MAX_TILES = 256
MAX_ENGINES = 32
MAX_COVERAGE = 512  # Two cargo coverage observations per bounded tile.
UInt = Annotated[int, Field(ge=0, le=2**32 - 2)]
CargoID = Annotated[int, Field(ge=0, le=63)]
IndustryID = Annotated[int, Field(ge=0, le=63999)]
RoadTypeID = Annotated[int, Field(ge=0, le=63)]
EngineID = Annotated[int, Field(ge=0, le=65534)]
MoneyGBP = Annotated[int, Field(ge=0, le=2**63 - 1)]


class PlanningFactError(ValueError):
    """Missing, incompatible or incoherent controlled planning input."""


class FactSource(Contract):
    """Semantic references, not assertions of native origin or process ownership."""

    world_observation_digest: Digest
    structural_digest: Digest
    production_digest: Digest
    world_id: Annotated[str, Field(min_length=1, max_length=64)]
    runtime_digest: Digest
    configuration_digest: Digest
    bridge_digest: Digest
    content_digest: Digest  # External installed-content manifest, not GSNewGRF IDs.
    map_width: Annotated[int, Field(ge=1, le=65536)]
    map_height: Annotated[int, Field(ge=1, le=65536)]

    def require_world(self, world: WorldPlanningObservation) -> None:
        context = world.context
        expected = (
            world.composition_digest,
            world.structural.structural_world_digest,
            world.production.production_digest,
            context.world.world_id,
            context.world.runtime_identity.sha256,
            context.configuration_digest,
            context.bridge.sha256,
            context.world.map_width,
            context.world.map_height,
        )
        actual = (
            self.world_observation_digest,
            self.structural_digest,
            self.production_digest,
            self.world_id,
            self.runtime_digest,
            self.configuration_digest,
            self.bridge_digest,
            self.map_width,
            self.map_height,
        )
        if actual != expected:
            raise PlanningFactError("supplemental source/observation identity mismatch")


class Region(Contract):
    x: UInt
    y: UInt
    width: Annotated[int, Field(ge=1, le=MAX_TILES)]
    height: Annotated[int, Field(ge=1, le=MAX_TILES)]

    @model_validator(mode="after")
    def bounded(self) -> Region:
        if self.width * self.height > MAX_TILES:
            raise PlanningFactError("region exceeds 256 tiles")
        return self


class TileFact(Contract):
    tile_id: UInt
    x: UInt
    y: UInt
    min_height: Annotated[int, Field(ge=0, le=255)]
    slope: Annotated[int, Field(ge=0, le=31)]
    buildable: bool
    water: bool
    coast: bool
    tree: bool
    farm: bool
    rock: bool
    rough: bool
    road: bool
    rail: bool
    water_transport: bool
    air_transport: bool
    industry_id: IndustryID | None  # Native invalid-industry sentinel normalized to None.


class CoverageFact(Contract):
    """1x1 potential stop coverage; neither a station nor measured consumption."""

    tile_id: UInt
    industry_id: IndustryID
    cargo_id: CargoID
    role: Literal["pickup", "delivery"]
    producer_count: Annotated[int, Field(ge=0, le=2**31 - 1)]
    acceptance_eighths: Annotated[int, Field(ge=0, le=2**31 - 1)]
    # Industry-specific geometry list membership must accompany aggregate cargo values.
    industry_covered: bool


class CoverageScope(Contract):
    industry_id: IndustryID
    cargo_id: CargoID
    role: Literal["pickup", "delivery"]


class EngineFact(Contract):
    engine_id: EngineID
    default_cargo_id: CargoID
    engine_road_type_id: RoadTypeID
    public_available: bool
    articulated: Literal[False]
    has_power_on_road: Literal[True]
    capacity_cargo_units: Annotated[int, Field(ge=1, le=65535)]
    purchase_cost_gbp: MoneyGBP
    running_cost_gbp_per_economy_year: MoneyGBP
    max_speed_native: Annotated[int, Field(ge=1, le=65535)]


class RoadFacts(Contract):
    road_type_id: Literal[0]  # Audited ordinary-road minimum; no tram/custom road.
    public_available: Literal[True]
    max_speed_native: Annotated[int, Field(ge=0, le=65535)]  # 0 = unlimited.
    road_piece_cost_gbp: MoneyGBP
    truck_stop_cost_gbp: MoneyGBP
    depot_cost_gbp: MoneyGBP
    currency: Literal["GBP"]


class ContentSettings(Contract):
    content_digest: Digest
    generation_seed: Annotated[int, Field(ge=0, lt=2**32 - 1)]
    modified_catchment: bool
    serve_neutral_industries: bool
    timekeeping: Literal["calendar"]
    effective_truck_stop_radius: Literal[3, 4]
    context: Literal["deity-public"]
    gameplay_newgrf_ids: tuple[()]  # No gameplay NewGRFs in minimum slice.

    @model_validator(mode="after")
    def catchment(self) -> ContentSettings:
        if self.effective_truck_stop_radius != (3 if self.modified_catchment else 4):
            raise PlanningFactError("catchment setting/radius mismatch")
        return self


class SupplementalPlanningFacts(Contract):
    schema_version: Literal[1]
    transport_mode: Literal["road"]
    source: FactSource
    region: Region
    settings: ContentSettings
    road: RoadFacts
    tiles: Annotated[tuple[TileFact, ...], Field(max_length=MAX_TILES)]
    coverage_scopes: Annotated[tuple[CoverageScope, ...], Field(max_length=2)]
    coverage: Annotated[tuple[CoverageFact, ...], Field(max_length=MAX_COVERAGE)]
    engines: Annotated[tuple[EngineFact, ...], Field(max_length=MAX_ENGINES)]
    capture_economy_date_before: Annotated[int, Field(ge=0, le=2**31 - 1)]
    capture_economy_date_after: Annotated[int, Field(ge=0, le=2**31 - 1)]

    @model_validator(mode="after")
    def coherent(self) -> SupplementalPlanningFacts:
        r, s = self.region, self.source
        if r.x + r.width > s.map_width or r.y + r.height > s.map_height:
            raise PlanningFactError("region outside map bounds")
        expected = {
            (y * s.map_width + x, x, y)
            for y in range(r.y, r.y + r.height)
            for x in range(r.x, r.x + r.width)
        }
        actual = [(t.tile_id, t.x, t.y) for t in self.tiles]
        if len(set(actual)) != len(actual) or set(actual) != expected:
            raise PlanningFactError("duplicate, invalid or incomplete region tile coverage")
        if s.content_digest != self.settings.content_digest:
            raise PlanningFactError("content/settings identity mismatch")
        if self.capture_economy_date_after < self.capture_economy_date_before:
            raise PlanningFactError("backward capture bracket")
        keys = [(c.tile_id, c.industry_id, c.cargo_id, c.role) for c in self.coverage]
        if len(set(keys)) != len(keys) or any(
            c.tile_id not in {t[0] for t in expected} for c in self.coverage
        ):
            raise PlanningFactError("duplicate or out-of-region coverage fact")
        scopes = [(c.industry_id, c.cargo_id, c.role) for c in self.coverage_scopes]
        required = {(t[0], *scope) for t in expected for scope in scopes}
        if len(set(scopes)) != len(scopes) or set(keys) != required:
            raise PlanningFactError("incomplete declared cargo coverage scope")
        object.__setattr__(
            self,
            "coverage_scopes",
            tuple(sorted(self.coverage_scopes, key=lambda c: (c.industry_id, c.cargo_id, c.role))),
        )
        ids = [e.engine_id for e in self.engines]
        if len(set(ids)) != len(ids):
            raise PlanningFactError("duplicate engine identity")
        if any(e.engine_road_type_id != self.road.road_type_id for e in self.engines):
            raise PlanningFactError("unsupported engine/road compatibility")
        object.__setattr__(self, "tiles", tuple(sorted(self.tiles, key=lambda t: t.tile_id)))
        object.__setattr__(
            self,
            "coverage",
            tuple(
                sorted(self.coverage, key=lambda c: (c.tile_id, c.industry_id, c.cargo_id, c.role))
            ),
        )
        object.__setattr__(self, "engines", tuple(sorted(self.engines, key=lambda e: e.engine_id)))
        return self

    def require_world(self, world: WorldPlanningObservation) -> None:
        self.source.require_world(world)
        month = world.production.qualification.current_month
        if (
            not month.start_date
            <= self.capture_economy_date_before
            <= self.capture_economy_date_after
            < month.end_date
        ):
            raise PlanningFactError("supplemental capture outside final M2 month")
        industries = {i.id for i in world.structural.inventory.observation.records}
        cargos = {c.cargo_id for c in world.structural.catalog.observation.records}
        capabilities = {
            c.industry_id: c for c in world.structural.capability.observation.capabilities
        }
        for t in self.tiles:
            if t.industry_id is not None and t.industry_id not in industries:
                raise PlanningFactError("unknown tile industry reference")
        for c in self.coverage:
            if c.industry_id not in industries or c.cargo_id not in cargos:
                raise PlanningFactError("unknown coverage industry/cargo reference")
            cap = capabilities[c.industry_id]
            pairs = cap.produces if c.role == "pickup" else cap.accepts
            if c.cargo_id not in pairs:
                raise PlanningFactError("coverage relationship not present in structure")
        if any(e.default_cargo_id not in cargos for e in self.engines):
            raise PlanningFactError("unknown engine default cargo")

    def to_bytes(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()

    @property
    def semantic_digest(self) -> str:
        return hashlib.sha256(self.to_bytes()).hexdigest()
