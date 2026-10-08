"""Bounded controlled road candidates, independent of historical full-map extraction."""

from collections import deque
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from hashlib import sha256
from itertools import product
from typing import Literal

from app.planning.canonical import world_manifest_hash
from app.planning.domain import (
    CargoDemand,
    ConstructionKind,
    EconomicAssumptions,
    InfrastructureCandidate,
    LocationKind,
    Mode,
    PlanningConstraints,
    PlanningLocation,
    PlanningScenario,
    PreparedWorldManifest,
    ResolvedSite,
    RoadFleetOption,
    SourceReference,
    Tile,
    VehicleDefinition,
    WorldReference,
)
from app.planning.p08_adapter import (
    MAX_PATH_EXPANSIONS,
    MAX_STATIONS_PER_ROLE,
    MAX_VEHICLES,
    POLICY_VERSION,
    BoundedRoadInput,
    Cargo,
    Industry,
    QualifiedSupply,
    RoadOutcome,
    adapt_planning_facts,
)
from app.planning.preparation.costs import validate_cost_units
from app.planning.preparation.failures import PreparationError
from app.simulation.openttd.prepared_source_correspondence import SourceTrust
from app.simulation.openttd.supplemental_planning_facts import (
    EngineFact,
    PlanningFactError,
    TileFact,
)

DIRECTIONS = (("north", 0, -1), ("east", 1, 0), ("south", 0, 1), ("west", -1, 0))


@dataclass(frozen=True)
class Benchmark:
    supply: QualifiedSupply
    producer: Industry
    acceptor: Industry
    cargo: Cargo
    quantity: int
    meaning: str = "historical-qualified-supply-transport-benchmark"
    unit: str = "cargo_units"
    planned_trips_per_vehicle: int = 1
    measured_consumption: None = None


@dataclass(frozen=True)
class Facility:
    tile_id: int
    front_tile_id: int
    orientation: Literal["north", "east", "south", "west"]


@dataclass(frozen=True)
class CandidateProvenance:
    candidate_id: str
    provenance_digest: str
    producer_id: int
    acceptor_id: int
    cargo_id: int
    source_tiles: tuple[int, ...]
    engine_id: int | None = None


@dataclass(frozen=True)
class ControlledRoadScenario:
    scenario: PlanningScenario
    input: BoundedRoadInput
    benchmark: Benchmark
    pickup: Facility
    delivery: Facility
    depot: Facility
    corridor: tuple[int, ...]
    candidate_provenance: tuple[CandidateProvenance, ...]
    search_expansions: int
    station_pairs_examined: int
    road_pieces: int
    fleet_count: int
    classification: str = "CONTROLLED_PLANNING_SCENARIO"
    trust: SourceTrust = SourceTrust.CONTROLLED_FIXTURE

    def require_real_executable_source(self) -> None:
        self.input.admitted.require_real_executable_source()


@dataclass(frozen=True)
class NoRoadScenario:
    code: RoadOutcome
    detail: str
    input: BoundedRoadInput


def vacant(t: TileFact) -> bool:
    return (
        t.buildable
        and t.slope == 0
        and t.industry_id is None
        and not any(
            (
                t.water,
                t.coast,
                t.tree,
                t.farm,
                t.rock,
                t.rough,
                t.road,
                t.rail,
                t.water_transport,
                t.air_transport,
            )
        )
    )


def neighbors(t: TileFact, tiles: dict[int, TileFact], width: int):
    """Covered cardinal adjacency only; no inferred terrain or row wrap."""
    for direction, dx, dy in DIRECTIONS:
        x, y = t.x + dx, t.y + dy
        n = tiles.get(y * width + x)
        if n is not None and (n.x, n.y) == (x, y) and n.min_height == t.min_height:
            yield direction, n


def select_benchmark(value: BoundedRoadInput) -> Benchmark | NoRoadScenario:
    positive = {(s.industry_id, s.cargo_id): s for s in value.supplies if s.quantity > 0}
    if not value.supplies:
        return NoRoadScenario(RoadOutcome.NO_ELIGIBLE_BENCHMARK, "qualified empty targets", value)
    if not positive:
        return NoRoadScenario(RoadOutcome.ZERO_POSITIVE_SUPPLY, "qualified supply is zero", value)
    # At most two admitted scopes, hence at most one distinct pickup/delivery OD.
    pickups = [s for s in value.facts.coverage_scopes if s.role == "pickup"]
    deliveries = [s for s in value.facts.coverage_scopes if s.role == "delivery"]
    if not pickups or not deliveries:
        return NoRoadScenario(RoadOutcome.INSUFFICIENT_COVERAGE, "two role scopes required", value)
    industries = {i.industry_id: i for i in value.industries}
    cargos = {c.cargo_id: c for c in value.cargos}
    for a, b in sorted(
        product(pickups, deliveries),
        key=lambda p: (p[0].industry_id, p[0].cargo_id, p[1].industry_id),
    ):
        s = positive.get((a.industry_id, a.cargo_id))
        if (
            s is not None
            and a.cargo_id == b.cargo_id
            and a.industry_id != b.industry_id
            and cargos[a.cargo_id].freight
            and a.cargo_id in industries[a.industry_id].produces
            and a.cargo_id in industries[b.industry_id].accepts
        ):
            return Benchmark(
                s,
                industries[a.industry_id],
                industries[b.industry_id],
                cargos[a.cargo_id],
                s.quantity,
            )
    return NoRoadScenario(RoadOutcome.NO_ELIGIBLE_BENCHMARK, "no compatible covered OD", value)


def station_tiles(value: BoundedRoadInput, b: Benchmark, role: str) -> tuple[int, ...]:
    industry = b.producer if role == "pickup" else b.acceptor
    covered = {
        c.tile_id
        for c in value.facts.coverage
        if c.industry_id == industry.industry_id
        and c.cargo_id == b.cargo.cargo_id
        and c.role == role
        and c.industry_covered
        and (c.producer_count > 0 if role == "pickup" else c.acceptance_eighths >= 8)
    }
    # Native industry-specific coverage is authoritative; anchor distance is only ranking.
    eligible = [t for t in value.facts.tiles if t.tile_id in covered and vacant(t)]
    eligible.sort(key=lambda t: (abs(t.x - industry.x) + abs(t.y - industry.y), t.tile_id))
    return tuple(t.tile_id for t in eligible[:MAX_STATIONS_PER_ROLE])


def shortest_path(
    start: int, end: int, tiles: dict[int, TileFact], width: int
) -> tuple[tuple[int, ...], int]:
    """Uniform road costs permit BFS; at most one expansion per covered tile."""
    pending = deque([start])
    parents: dict[int, int | None] = {start: None}
    expansions = 0
    while pending:
        i = pending.popleft()
        expansions += 1
        if i == end:
            path = [i]
            while parents[path[-1]] is not None:
                parent = parents[path[-1]]
                assert parent is not None
                path.append(parent)
            return tuple(reversed(path)), expansions
        for _, n in neighbors(tiles[i], tiles, width):
            if n.tile_id not in parents:
                parents[n.tile_id] = i
                pending.append(n.tile_id)
    return (), expansions


def find_depot(path: tuple[int, ...], tiles: dict[int, TileFact], width: int) -> Facility | None:
    # Road must connect to a corridor interior, never a terminal station footprint.
    for i in sorted(tiles):
        if i in path:
            continue
        for direction, n in neighbors(tiles[i], tiles, width):
            if n.tile_id in path[1:-1]:
                return Facility(i, n.tile_id, direction)
    return None


def facing(a: TileFact, b: TileFact) -> Literal["north", "east", "south", "west"]:
    return next(d for d, dx, dy in DIRECTIONS if (a.x + dx, a.y + dy) == (b.x, b.y))


def generate_road_scenario(value: BoundedRoadInput) -> ControlledRoadScenario | NoRoadScenario:
    """Return one candidate set or explicit bounded infeasibility; never invoke P05."""
    # Frozen dataclasses can still be manually constructed: verify adapter-issued mapping.
    if not isinstance(value, BoundedRoadInput):
        raise PlanningFactError("typed adapter output required")
    authoritative = adapt_planning_facts(value.admitted, value.policy)
    if value != authoritative:
        raise PlanningFactError("conflicting adapter mapping/provenance")
    b = select_benchmark(value)
    if isinstance(b, NoRoadScenario):
        return b
    engines = [
        e
        for e in value.facts.engines
        if e.public_available
        and e.default_cargo_id == b.cargo.cargo_id
        and e.engine_road_type_id == value.facts.road.road_type_id
    ]
    if not engines:
        return NoRoadScenario(
            RoadOutcome.INVALID_ENGINE_COMPATIBILITY,
            "no available default-cargo road engine",
            value,
        )
    # Choose first capacity-feasible engine, not an economically optimal engine.
    engines = [
        e
        for e in engines
        if (b.quantity + e.capacity_cargo_units - 1) // e.capacity_cargo_units <= MAX_VEHICLES
    ]
    if not engines:
        return NoRoadScenario(RoadOutcome.CAPACITY_INFEASIBLE, "fleet exceeds 64 vehicles", value)
    engine = engines[0]
    tiles = {t.tile_id: t for t in value.facts.tiles if vacant(t)}
    pickups, deliveries = station_tiles(value, b, "pickup"), station_tiles(value, b, "delivery")
    if not pickups or not deliveries:
        adequate_roles = {
            c.role
            for c in value.facts.coverage
            if c.industry_covered
            and (c.producer_count > 0 if c.role == "pickup" else c.acceptance_eighths >= 8)
        }
        code = (
            RoadOutcome.NO_STATION_PLACEMENT
            if adequate_roles == {"pickup", "delivery"}
            else RoadOutcome.MISSING_CATCHMENT
        )
        return NoRoadScenario(code, "no vacant industry-covered stop for both roles", value)
    expansions, pairs, connected = 0, 0, False
    for a, z in product(pickups, deliveries):
        pairs += 1
        if a == z:
            continue
        path, work = shortest_path(a, z, tiles, value.manifest.width_tiles)
        expansions += work
        if expansions > MAX_PATH_EXPANSIONS:
            return NoRoadScenario(
                RoadOutcome.SEARCH_LIMIT_EXCEEDED,
                "aggregate path expansion bound exceeded",
                value,
            )
        if len(path) < 3:
            continue
        connected = True
        depot = find_depot(path, tiles, value.manifest.width_tiles)
        if depot is None:
            continue
        pickup = Facility(a, path[1], facing(tiles[a], tiles[path[1]]))
        delivery = Facility(z, path[-2], facing(tiles[z], tiles[path[-2]]))
        return assemble(value, b, engine, pickup, delivery, depot, path, expansions, pairs)
    return NoRoadScenario(
        RoadOutcome.NO_DEPOT_PLACEMENT if connected else RoadOutcome.NO_BOUNDED_CORRIDOR,
        "bounded first-four-stop search exhausted; no feasibility outside this slice implied",
        value,
    )


def assemble(
    value: BoundedRoadInput,
    b: Benchmark,
    engine: EngineFact,
    pickup: Facility,
    delivery: Facility,
    depot: Facility,
    path: tuple[int, ...],
    expansions: int,
    pairs: int,
) -> ControlledRoadScenario | NoRoadScenario:
    def tile(i: int) -> Tile:
        return Tile(x=i % value.manifest.width_tiles, y=i // value.manifest.width_tiles)

    source = SourceReference(
        source_kind="p08-controlled-facts",
        source_id="road-batch",
        source_version=POLICY_VERSION,
        source_digest=value.provenance.digest,
    )
    origin, destination = f"industry-{b.producer.industry_id}", f"industry-{b.acceptor.industry_id}"
    locations = [
        PlanningLocation(
            location_id=origin,
            tile=Tile(x=b.producer.x, y=b.producer.y),
            kind=LocationKind.INDUSTRY_ORIGIN,
            permitted_modes=(Mode.ROAD,),
            source=source,
        ),
        PlanningLocation(
            location_id=destination,
            tile=Tile(x=b.acceptor.x, y=b.acceptor.y),
            kind=LocationKind.INDUSTRY_DESTINATION,
            permitted_modes=(Mode.ROAD,),
            source=source,
        ),
    ]
    candidates, provenance = [], []
    site_ids = (
        f"pickup-{pickup.tile_id}",
        f"delivery-{delivery.tile_id}",
        f"depot-{depot.tile_id}",
    )
    for site_id, facility, serves in zip(
        site_ids, (pickup, delivery, depot), (origin, destination, None), strict=True
    ):
        is_depot = serves is None
        location = PlanningLocation(
            location_id=site_id,
            tile=tile(facility.tile_id),
            kind=LocationKind.DEPOT_CANDIDATE if is_depot else LocationKind.STATION_CANDIDATE,
            permitted_modes=(Mode.ROAD,),
            footprint_width_tiles=1,
            footprint_height_tiles=1,
            serves_location_id=serves,
            facility_class="road" if is_depot else "truck",
            source=source,
            orientation=facility.orientation,
        )
        locations.append(location)
        cid = f"build-{site_id}"
        candidates.append(
            InfrastructureCandidate(
                candidate_id=cid,
                mode=Mode.ROAD,
                kind=ConstructionKind.DEPOT if is_depot else ConstructionKind.STATION,
                site_id=site_id,
                footprint_width_tiles=1,
                footprint_height_tiles=1,
                orientation=location.orientation,
                estimated_build_cost_gbp=Decimal(
                    value.facts.road.depot_cost_gbp
                    if is_depot
                    else value.facts.road.truck_stop_cost_gbp
                ),
                source=source,
            )
        )
        provenance.append(
            CandidateProvenance(
                cid,
                value.provenance.digest,
                b.producer.industry_id,
                b.acceptor.industry_id,
                b.cargo.cargo_id,
                (facility.tile_id, facility.front_tile_id),
            )
        )
    cid = "corridor-" + sha256(",".join(map(str, path)).encode()).hexdigest()[:24]
    # Two road pieces per nonstation corridor tile, plus one depot entrance piece.
    # Station/depot base charges include their footprints; do not charge them again.
    pieces = 2 * (len(path) - 2) + 1
    candidates.append(
        InfrastructureCandidate(
            candidate_id=cid,
            mode=Mode.ROAD,
            kind=ConstructionKind.SEGMENT,
            origin_id=site_ids[0],
            destination_id=site_ids[1],
            tiles=tuple(tile(i) for i in path),
            estimated_build_cost_gbp=Decimal(pieces * value.facts.road.road_piece_cost_gbp),
            source=source,
        )
    )
    provenance.append(
        CandidateProvenance(
            cid,
            value.provenance.digest,
            b.producer.industry_id,
            b.acceptor.industry_id,
            b.cargo.cargo_id,
            path,
        )
    )
    with localcontext() as context:
        context.prec = 100
        daily = (Decimal(engine.running_cost_gbp_per_economy_year) / Decimal(365)).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_EVEN
        )
        speed = Decimal(engine.max_speed_native) * Decimal("1.00584")
        if value.facts.road.max_speed_native:
            speed = min(speed, Decimal(value.facts.road.max_speed_native) * Decimal("2.01168"))
    fleet = RoadFleetOption(
        option_id=f"fleet-{engine.engine_id}",
        mode=Mode.ROAD,
        vehicle=VehicleDefinition(
            vehicle_type=f"road-engine-{engine.engine_id}",
            capacity_cargo_units=engine.capacity_cargo_units,
            purchase_cost_gbp=Decimal(engine.purchase_cost_gbp),
            running_cost_gbp_per_day=daily,
            speed_km_per_hour=speed,
            compatible_cargo_types=(b.cargo.identifier,),
        ),
        road_vehicle_class="road",
        depot_class="road",
        available_from_day=0,
        available_through_day=0,
        source=source,
    )
    count = (b.quantity + engine.capacity_cargo_units - 1) // engine.capacity_cargo_units
    capex = sum((c.estimated_build_cost_gbp for c in candidates), Decimal(0))
    capex += Decimal(engine.purchase_cost_gbp) * count
    if value.policy.budget_gbp is not None and capex > value.policy.budget_gbp:
        return NoRoadScenario(RoadOutcome.COST_INFEASIBLE, "benchmark capex exceeds budget", value)
    try:
        validate_cost_units(
            [
                *(c.estimated_build_cost_gbp for c in candidates),
                Decimal(engine.purchase_cost_gbp) * count,
                daily,
                *([] if value.policy.budget_gbp is None else [value.policy.budget_gbp]),
            ],
            value.manifest.source_digest,
        )
    except PreparationError:
        return NoRoadScenario(RoadOutcome.COST_INFEASIBLE, "P05 fixed-point range exceeded", value)
    sites = []
    for location in locations:
        site = ResolvedSite.model_validate(
            location.model_dump(exclude={"source", "world_reference"})
        )
        if location.location_id in (origin, destination):
            site = site.model_copy(
                update={
                    "world_kind": "industry",
                    "world_id": b.producer.industry_id
                    if location.location_id == origin
                    else b.acceptor.industry_id,
                }
            )
        sites.append(site)
    # Candidate-dependent manifest projection, from the admitted controlled source identity.
    manifest = PreparedWorldManifest.model_validate_json(
        value.manifest.model_copy(
            update={
                "resolved_sites": tuple(sites),
                "cargo_types": (b.cargo.identifier,),
                "vehicle_types": (fleet.vehicle.vehicle_type,),
                "buildable_tiles": tuple(tile(t.tile_id) for t in value.facts.tiles if vacant(t)),
            }
        ).model_dump_json()
    )
    if (
        any(
            (
                value.manifest.resolved_sites,
                value.manifest.cargo_types,
                value.manifest.vehicle_types,
                value.manifest.buildable_tiles,
            )
        )
        and manifest != value.manifest
    ):
        return NoRoadScenario(
            RoadOutcome.CONFLICTING_IDENTITIES,
            "supplied candidate-dependent manifest differs from projection",
            value,
        )
    fingerprint = world_manifest_hash(manifest)
    locations = [
        location.model_copy(
            update={
                "world_reference": WorldReference(
                    world_fingerprint=fingerprint,
                    kind="industry",
                    world_id=b.producer.industry_id
                    if location.location_id == origin
                    else b.acceptor.industry_id,
                )
            }
        )
        if location.location_id in (origin, destination)
        else location
        for location in locations
    ]
    scenario = PlanningScenario(
        schema_version=1,
        scenario_id="controlled-p08-road",
        scenario_version=POLICY_VERSION,
        world_fingerprint=fingerprint,
        world_manifest=manifest,
        openttd_version=manifest.openttd_version,
        base_set_name=manifest.base_set_name,
        base_set_version=manifest.base_set_version,
        width_tiles=manifest.width_tiles,
        height_tiles=manifest.height_tiles,
        seed=manifest.seed,
        start_date=value.policy.start_date,
        horizon_days=value.policy.horizon_days,
        supported_modes=(Mode.ROAD,),
        locations=tuple(locations),
        cargo_demands=(
            CargoDemand(
                demand_id=f"benchmark-{b.producer.industry_id}-{b.cargo.cargo_id}-{b.acceptor.industry_id}",
                cargo_type=b.cargo.identifier,
                origin_id=origin,
                destination_id=destination,
                quantity=b.quantity,
                unit="cargo_units",
                earliest_day=0,
                latest_delivery_day=value.policy.horizon_days - 1,
                source=SourceReference(
                    source_kind="p08-benchmark-policy",
                    source_id=POLICY_VERSION,
                    source_digest=value.provenance.digest,
                ),
            ),
        ),
        fleet_options=(fleet,),
        infrastructure_candidates=tuple(candidates),
        economic_assumptions=EconomicAssumptions(
            currency="GBP", model_name="controlled-road-batch", model_version="1"
        ),
        constraints=PlanningConstraints(
            permitted_modes=(Mode.ROAD,), budget_gbp=value.policy.budget_gbp
        ),
    )
    provenance.append(
        CandidateProvenance(
            fleet.option_id,
            value.provenance.digest,
            b.producer.industry_id,
            b.acceptor.industry_id,
            b.cargo.cargo_id,
            (depot.tile_id,),
            engine.engine_id,
        )
    )
    return ControlledRoadScenario(
        scenario,
        value,
        b,
        pickup,
        delivery,
        depot,
        path,
        tuple(provenance),
        expansions,
        pairs,
        pieces,
        count,
    )
