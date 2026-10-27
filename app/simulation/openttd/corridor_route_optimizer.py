"""Deterministic map-to-route optimization for the D5 corridor freight plan.

The D5 freight contract originally baked the D4 witness path into both the
Python plan and the GameScript package.  This module supplies the missing
production step: a bounded map/graph input is turned into P05 planning
candidates, the existing ``optimize_candidate_network`` solver chooses one
route, and the selected planner decision is converted into the D5
``FreightPlan`` (schema 2) whose witness is the exact tile sequence the
GameScript receives.

Objective and constraints (baseline, deliberately small):

* Objective: minimize planned CAPEX (the P05 solver's existing objective),
  then the solver's deterministic lexicographic tie-break.  A route candidate
  is one contiguous sequence of available tiles between one pickup stop and
  one delivery stop; its road-piece estimate is
  ``2 * (len(path) - 2) + 1``, matching the controlled P08 road model, plus
  any supplied source-backed per-tile cost.
* Alternatives: every supplied feasible tile set is searched with a bounded
  k-shortest *simple* path enumeration, so the same pickup/delivery endpoints
  can carry multiple distinct candidate geometries.  P05 then chooses among
  them by CAPEX and its deterministic tie-break; the selected geometry is the
  one bound into the D5 plan and wire request.
* Constraints: 3..``MAX_OPTIMIZED_ROUTE_TILES`` unique, cardinally adjacent
  tiles; endpoints are pickup/delivery stop candidates; exactly one depot
  candidate adjacent to exactly one interior route tile; every tile is in the
  supplied available-tile set; the purchase quote must be positive and within
  both the per-operation ceiling and, when supplied, available company funds.
* Limitations: this is not a general vehicle pathfinder, it does not model
  bridges/tunnels/slopes/traffic, and it does not choose cargo, industries,
  engine policy or the fifteen-exchange schedule.  Those remain the D5
  contract's fixed, independently admitted parameters.  The caller must
  supply authoritative feasible tiles; the optimizer never invents them.

The module is offline only: it never launches OpenTTD or contacts an
AdminPort.
"""

from __future__ import annotations

import hashlib
from collections import deque
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from app.planning.canonical import plan_hash, scenario_hash, world_manifest_hash
from app.planning.domain import (
    CargoDemand,
    ConstructionKind,
    EconomicAssumptions,
    EstimatedPlanMetrics,
    ExecutionPlan,
    InfrastructureCandidate,
    LocationKind,
    Mode,
    NetworkSelection,
    PlanningConstraints,
    PlanningLocation,
    PlanningScenario,
    PreparedWorldManifest,
    ResolvedSite,
    RoadFleetOption,
    SourceReference,
    SupplyLimit,
    Tile,
    VehicleDefinition,
)
from app.planning.optimizer import OptimizerFailure, optimize_candidate_network
from app.planning.validation import validate_execution_plan
from app.simulation.openttd.supplemental_planning_facts import TileFact

MIN_OPTIMIZED_ROUTE_TILES = 3
MAX_OPTIMIZED_ROUTE_TILES = 24
MAX_ROUTE_CANDIDATES = 256
ROUTE_PLAN_SCHEMA_VERSION = 2


class RouteOptimizationError(ValueError):
    """The bounded map cannot produce an admissible corridor route."""


@dataclass(frozen=True)
class RouteOptimizerInput:
    """One bounded map snapshot; every tile id is a 256x256-safe TileID."""

    map_width: int
    map_height: int
    available_tiles: tuple[int, ...]
    pickup_candidates: tuple[int, ...]
    delivery_candidates: tuple[int, ...]
    depot_candidates: tuple[int, ...]
    vehicle_type: str
    capacity_cargo_units: int
    purchase_cost_gbp: Decimal
    running_cost_gbp_per_day: Decimal
    speed_km_per_hour: Decimal
    road_piece_cost_gbp: Decimal
    truck_stop_cost_gbp: Decimal
    depot_cost_gbp: Decimal
    cargo_type: str = "cargo-1"
    cargo_id: int = 1
    pickup_industry: int = 0
    delivery_industry: int = 1
    source_digest: str | None = None
    budget_gbp: Decimal | None = None
    available_funds_gbp: Decimal | None = None
    max_purchase_cost_gbp: Decimal | None = None
    # Optional source-backed per-tile road cost (terrain/land cost).  The
    # route objective is total planned CAPEX, so a per-tile cost can make a
    # longer but cheaper corridor beat a shorter expensive one.  Empty means
    # the uniform ``road_piece_cost_gbp`` model.
    tile_costs_gbp: tuple[tuple[int, Decimal], ...] = ()


@dataclass(frozen=True)
class OptimizedRoute:
    """The selected planning decision and its D5-safe geometry."""

    scenario: PlanningScenario
    execution_plan: ExecutionPlan
    metrics: EstimatedPlanMetrics
    pickup: int
    pickup_front: int
    delivery: int
    delivery_front: int
    depot: int
    depot_front: int
    route: tuple[int, ...]
    candidate_id: str
    cargo_type: str
    cargo_id: int
    pickup_industry: int
    delivery_industry: int

    @property
    def plan_digest(self) -> str:
        return plan_hash(self.execution_plan)

    @property
    def scenario_digest(self) -> str:
        return scenario_hash(self.scenario)

    def freight_plan(
        self,
        *,
        company: int = 0,
        expected_funds: int,
        max_cost: int,
        schedule: tuple[str, ...],
    ):
        """Build the D5 wire plan from this optimizer decision.

        Imported lazily so the wire contract remains usable without the
        optimizer and this module does not create an import cycle.
        """
        from app.simulation.openttd.corridor_freight import FreightPlan

        return FreightPlan(
            schema_version=ROUTE_PLAN_SCHEMA_VERSION,
            company=company,
            cargo=self.cargo_id,
            pickup=self.pickup,
            pickup_front=self.pickup_front,
            delivery=self.delivery,
            delivery_front=self.delivery_front,
            depot=self.depot,
            depot_front=self.depot_front,
            pickup_industry=self.pickup_industry,
            delivery_industry=self.delivery_industry,
            expected_funds=expected_funds,
            max_cost=max_cost,
            witness=self.route,
            schedule=schedule,
        )


def _tile(tile_id: int, width: int, height: int) -> Tile:
    if not 0 <= tile_id <= 65535:
        raise RouteOptimizationError("route tile exceeds the 256x256-safe TileID bound")
    x, y = tile_id % width, tile_id // width
    if x >= width or y >= height:
        raise RouteOptimizationError("route tile lies outside the supplied map")
    return Tile(x=x, y=y)


def _require_distinct(label: str, values: tuple[int, ...]) -> None:
    if len(values) != len(set(values)):
        raise RouteOptimizationError(f"{label} contains duplicate tiles")


def _available_source(value: RouteOptimizerInput) -> str:
    if value.source_digest is not None:
        if len(value.source_digest) != 64 or any(
            character not in "0123456789abcdef" for character in value.source_digest
        ):
            raise RouteOptimizationError("source digest must be 64 lowercase hex characters")
        return value.source_digest
    payload = ",".join(
        (
            str(value.map_width),
            str(value.map_height),
            ",".join(map(str, sorted(value.available_tiles))),
            ",".join(map(str, sorted(value.pickup_candidates))),
            ",".join(map(str, sorted(value.delivery_candidates))),
            ",".join(map(str, sorted(value.depot_candidates))),
        )
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _validated_input(value: RouteOptimizerInput) -> None:
    if not 1 <= value.map_width <= 256 or not 1 <= value.map_height <= 256:
        raise RouteOptimizationError("map dimensions must be 1..256")
    if not value.available_tiles:
        raise RouteOptimizationError("no available corridor tiles supplied")
    if not value.pickup_candidates or not value.delivery_candidates:
        raise RouteOptimizationError("pickup and delivery stop candidates are required")
    if not value.depot_candidates:
        raise RouteOptimizationError("a depot candidate is required")
    for label, tiles in (
        ("available", value.available_tiles),
        ("pickup", value.pickup_candidates),
        ("delivery", value.delivery_candidates),
        ("depot", value.depot_candidates),
    ):
        _require_distinct(label, tiles)
        for tile in tiles:
            _tile(tile, value.map_width, value.map_height)
    available = set(value.available_tiles)
    for label, tiles in (
        ("pickup", value.pickup_candidates),
        ("delivery", value.delivery_candidates),
        ("depot", value.depot_candidates),
    ):
        if not set(tiles) <= available:
            raise RouteOptimizationError(f"{label} candidate is not an available tile")
    if set(value.pickup_candidates) & set(value.delivery_candidates):
        raise RouteOptimizationError("pickup and delivery candidates overlap")
    if value.capacity_cargo_units <= 0:
        raise RouteOptimizationError("vehicle capacity must be positive")
    for label, amount in (
        ("purchase", value.purchase_cost_gbp),
        ("road piece", value.road_piece_cost_gbp),
        ("truck stop", value.truck_stop_cost_gbp),
        ("depot", value.depot_cost_gbp),
    ):
        if not amount.is_finite() or amount < 0:
            raise RouteOptimizationError(f"{label} cost must be finite and non-negative")
    if value.purchase_cost_gbp <= 0:
        raise RouteOptimizationError("vehicle purchase quote must be positive")
    if value.max_purchase_cost_gbp is not None and (
        value.max_purchase_cost_gbp <= 0 or value.purchase_cost_gbp > value.max_purchase_cost_gbp
    ):
        raise RouteOptimizationError("vehicle purchase exceeds the per-operation ceiling")
    if (
        value.available_funds_gbp is not None
        and value.purchase_cost_gbp > value.available_funds_gbp
    ):
        raise RouteOptimizationError("vehicle purchase exceeds available funds")
    if value.budget_gbp is not None and value.budget_gbp < 0:
        raise RouteOptimizationError("budget must be non-negative")
    _require_distinct("tile cost", tuple(tile for tile, _ in value.tile_costs_gbp))
    for tile, amount in value.tile_costs_gbp:
        _tile(tile, value.map_width, value.map_height)
        if not amount.is_finite() or amount < 0:
            raise RouteOptimizationError("tile cost must be finite and non-negative")
    if not value.vehicle_type:
        raise RouteOptimizationError("vehicle type is required")
    if not value.cargo_type:
        raise RouteOptimizationError("cargo type is required")


def _segment_cost(value: RouteOptimizerInput, path: tuple[int, ...]) -> Decimal:
    """Total planned road CAPEX for one candidate corridor."""
    extra = dict(value.tile_costs_gbp)
    return value.road_piece_cost_gbp * (2 * (len(path) - 2) + 1) + sum(
        (extra.get(tile, Decimal(0)) for tile in path), Decimal(0)
    )


def _tile_facts(
    value: RouteOptimizerInput,
) -> dict[int, TileFact]:
    facts: dict[int, TileFact] = {}
    for tile_id in value.available_tiles:
        tile = _tile(tile_id, value.map_width, value.map_height)
        facts[tile_id] = TileFact(
            tile_id=tile_id,
            x=tile.x,
            y=tile.y,
            min_height=0,
            slope=0,
            buildable=True,
            water=False,
            coast=False,
            tree=False,
            farm=False,
            rock=False,
            rough=False,
            road=False,
            rail=False,
            water_transport=False,
            air_transport=False,
            industry_id=None,
        )
    return facts


def _adjacent(tile: int, interior: set[int], width: int) -> bool:
    x, y = tile % width, tile // width
    return any(abs(x - other % width) + abs(y - other // width) == 1 for other in interior)


def _candidate_routes(
    value: RouteOptimizerInput, facts: dict[int, TileFact]
) -> list[tuple[tuple[int, ...], int, int, int]]:
    """Return (path, pickup, delivery, depot) candidates, deterministically.

    Every supplied available tile is a feasible map tile (the caller is
    responsible for sourcing that set).  For each pickup/delivery pair the
    bounded k-shortest-simple-path enumeration returns *all* distinct feasible
    geometries up to the candidate bound, not just the single BFS shortest
    path.  That is what lets P05 choose among genuine competing corridors
    instead of round-tripping one witness.

    Sorting precedes path search so ties never depend on hash or input
    ordering.  A path is admissible only when exactly one interior tile is
    cardinally joined to one of the supplied depot candidates (the depot
    itself stays off the corridor).
    """
    candidates: dict[tuple[tuple[int, ...], int, int, int], None] = {}
    for pickup in sorted(value.pickup_candidates):
        for delivery in sorted(value.delivery_candidates):
            if pickup == delivery:
                continue
            paths = _bounded_paths(
                pickup,
                delivery,
                facts,
                value.map_width,
                limit=MAX_ROUTE_CANDIDATES,
                max_length=MAX_OPTIMIZED_ROUTE_TILES,
            )
            for path in paths:
                if not MIN_OPTIMIZED_ROUTE_TILES <= len(path) <= MAX_OPTIMIZED_ROUTE_TILES:
                    continue
                interior = set(path[1:-1])
                depots = [
                    depot
                    for depot in sorted(value.depot_candidates)
                    if depot not in path
                    and sum(_adjacent(depot, {tile}, value.map_width) for tile in interior) == 1
                ]
                if not depots:
                    # A depot must join exactly one corridor interior tile.
                    # There is no implicit fallback: an unmatched candidate
                    # is not a valid D5 depot join and is skipped.
                    continue
                candidates[(path, pickup, delivery, depots[0])] = None
    ordered = sorted(
        candidates,
        key=lambda item: (len(item[0]), item[0], item[1], item[2], item[3]),
    )
    if not ordered:
        raise RouteOptimizationError(
            "no connected pickup-delivery corridor with an adjacent depot candidate"
        )
    if len(ordered) > MAX_ROUTE_CANDIDATES:
        raise RouteOptimizationError("route candidate bound exceeded")
    return [(path, pickup, delivery, depot) for path, pickup, delivery, depot in ordered]


def _edge(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def _bfs_path(
    start: int,
    end: int,
    facts: dict[int, TileFact],
    width: int,
    *,
    blocked_nodes: frozenset[int] = frozenset(),
    blocked_edges: frozenset[tuple[int, int]] = frozenset(),
) -> tuple[int, ...]:
    """One deterministic shortest simple path under blocked nodes/edges."""
    pending = deque([start])
    parents: dict[int, int | None] = {start: None}
    while pending:
        current = pending.popleft()
        if current == end:
            path = [current]
            while parents[path[-1]] is not None:
                parent = parents[path[-1]]
                assert parent is not None
                path.append(parent)
            return tuple(reversed(path))
        tile = facts.get(current)
        if tile is None:
            continue
        x, y = tile.x, tile.y
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            neighbour = facts.get((y + dy) * width + (x + dx))
            if neighbour is None or (neighbour.x, neighbour.y) != (x + dx, y + dy):
                continue
            identity = neighbour.tile_id
            if identity in blocked_nodes or identity in parents:
                continue
            if _edge(current, identity) in blocked_edges:
                continue
            parents[identity] = current
            pending.append(identity)
    return ()


def _bounded_paths(
    start: int,
    end: int,
    facts: dict[int, TileFact],
    width: int,
    *,
    limit: int,
    max_length: int,
) -> list[tuple[int, ...]]:
    """Deterministic bounded k-shortest *simple* path enumeration (Yen's).

    The first path is the BFS shortest path.  Each further path is the
    shortest spur deviation from an already accepted path with the accepted
    prefixes' next edges removed, which enumerates genuinely distinct simple
    geometries in (length, tile-sequence) order.  The result is bounded by
    ``limit`` and ``max_length``; it never invents tiles outside ``facts``.
    """
    first = _bfs_path(start, end, facts, width)
    if not first or len(first) > max_length:
        return []
    accepted: list[tuple[int, ...]] = [first]
    pending: set[tuple[int, ...]] = set()
    while len(accepted) < limit:
        previous = accepted[-1]
        for index in range(len(previous) - 1):
            spur = previous[index]
            root = previous[: index + 1]
            blocked_edges = {
                _edge(path[index], path[index + 1])
                for path in accepted
                if path[: index + 1] == root
            }
            spur_path = _bfs_path(
                spur,
                end,
                facts,
                width,
                blocked_nodes=frozenset(root[:-1]),
                blocked_edges=frozenset(blocked_edges),
            )
            if not spur_path:
                continue
            total = root[:-1] + spur_path
            if len(total) > max_length or total in accepted or total in pending:
                continue
            pending.add(total)
        if not pending:
            break
        next_path = min(pending, key=lambda path: (len(path), path))
        pending.remove(next_path)
        accepted.append(next_path)
    return accepted


def _location(
    location_id: str,
    tile: Tile,
    kind: LocationKind,
    source: SourceReference,
    *,
    serves: str | None = None,
    facility_class: str | None = None,
) -> PlanningLocation:
    return PlanningLocation(
        location_id=location_id,
        tile=tile,
        kind=kind,
        permitted_modes=(Mode.ROAD,),
        footprint_width_tiles=1,
        footprint_height_tiles=1,
        serves_location_id=serves,
        facility_class=facility_class,
        source=source,
    )


def _scenario(
    value: RouteOptimizerInput,
    candidates: list[tuple[tuple[int, ...], int, int, int]],
    source_digest: str,
) -> tuple[PlanningScenario, dict[str, int]]:
    source = SourceReference(
        source_kind="route-optimizer-map",
        source_id="bounded-corridor-map",
        source_version="1",
        source_digest=source_digest,
    )
    origin_id, destination_id = "industry-origin", "industry-destination"
    pickup_tiles = sorted({pickup for _, pickup, _, _ in candidates})
    delivery_tiles = sorted({delivery for _, _, delivery, _ in candidates})
    depot_tiles = sorted({depot for _, _, _, depot in candidates})
    locations: list[PlanningLocation] = [
        _location(
            origin_id,
            _tile(pickup_tiles[0], value.map_width, value.map_height),
            LocationKind.INDUSTRY_ORIGIN,
            source,
        ),
        _location(
            destination_id,
            _tile(delivery_tiles[0], value.map_width, value.map_height),
            LocationKind.INDUSTRY_DESTINATION,
            source,
        ),
    ]
    for role, tiles, serves, kind, facility in (
        ("pickup", pickup_tiles, origin_id, LocationKind.STATION_CANDIDATE, "truck"),
        ("delivery", delivery_tiles, destination_id, LocationKind.STATION_CANDIDATE, "truck"),
        ("depot", depot_tiles, None, LocationKind.DEPOT_CANDIDATE, "road"),
    ):
        for tile_id in tiles:
            locations.append(
                _location(
                    f"{role}-{tile_id}",
                    _tile(tile_id, value.map_width, value.map_height),
                    kind,
                    source,
                    serves=serves,
                    facility_class=facility,
                )
            )
    candidate_models: list[InfrastructureCandidate] = []
    for location in locations:
        if location.kind is LocationKind.DEPOT_CANDIDATE:
            kind, cost = ConstructionKind.DEPOT, value.depot_cost_gbp
        elif location.kind is LocationKind.STATION_CANDIDATE:
            kind, cost = ConstructionKind.STATION, value.truck_stop_cost_gbp
        else:
            continue
        candidate_models.append(
            InfrastructureCandidate(
                candidate_id=f"build-{location.location_id}",
                mode=Mode.ROAD,
                kind=kind,
                site_id=location.location_id,
                footprint_width_tiles=1,
                footprint_height_tiles=1,
                estimated_build_cost_gbp=cost,
                source=source,
            )
        )
    for path, pickup, delivery, depot in candidates:
        digest = hashlib.sha256(",".join(map(str, path)).encode()).hexdigest()[:24]
        candidate_models.append(
            InfrastructureCandidate(
                candidate_id=f"corridor-{digest}",
                mode=Mode.ROAD,
                kind=ConstructionKind.SEGMENT,
                origin_id=f"pickup-{pickup}",
                destination_id=f"delivery-{delivery}",
                tiles=tuple(_tile(tile_id, value.map_width, value.map_height) for tile_id in path),
                estimated_build_cost_gbp=_segment_cost(value, path),
                source=source,
            )
        )
    sites = tuple(
        ResolvedSite.model_validate(location.model_dump(exclude={"source", "world_reference"}))
        for location in locations
    )
    manifest = PreparedWorldManifest(
        schema_version=1,
        source_digest=source_digest,
        openttd_version="15.3",
        base_set_name="OpenGFX",
        base_set_version="8.0",
        width_tiles=value.map_width,
        height_tiles=value.map_height,
        seed=0,
        resolved_sites=sites,
        cargo_types=(value.cargo_type,),
        vehicle_types=(value.vehicle_type,),
        buildable_tiles=tuple(
            _tile(tile_id, value.map_width, value.map_height)
            for tile_id in sorted(value.available_tiles)
        ),
    )
    fingerprint = world_manifest_hash(manifest)
    fleet = RoadFleetOption(
        option_id="fleet-optimizer",
        mode=Mode.ROAD,
        vehicle=VehicleDefinition(
            vehicle_type=value.vehicle_type,
            capacity_cargo_units=value.capacity_cargo_units,
            purchase_cost_gbp=value.purchase_cost_gbp,
            running_cost_gbp_per_day=value.running_cost_gbp_per_day,
            speed_km_per_hour=value.speed_km_per_hour,
            compatible_cargo_types=(value.cargo_type,),
        ),
        road_vehicle_class="road",
        depot_class="road",
        available_from_day=0,
        available_through_day=0,
        source=source,
    )
    budget = value.budget_gbp
    if value.available_funds_gbp is not None:
        budget = (
            value.available_funds_gbp if budget is None else min(budget, value.available_funds_gbp)
        )
    scenario = PlanningScenario(
        schema_version=1,
        scenario_id="corridor-route-optimizer",
        scenario_version="1",
        world_fingerprint=fingerprint,
        world_manifest=manifest,
        openttd_version="15.3",
        base_set_name="OpenGFX",
        base_set_version="8.0",
        width_tiles=value.map_width,
        height_tiles=value.map_height,
        seed=0,
        start_date=date(1950, 1, 1),
        horizon_days=1,
        supported_modes=(Mode.ROAD,),
        locations=tuple(locations),
        cargo_demands=(
            CargoDemand(
                demand_id="corridor-demand",
                cargo_type=value.cargo_type,
                origin_id=origin_id,
                destination_id=destination_id,
                quantity=1,
                unit="cargo_units",
                earliest_day=0,
                latest_delivery_day=0,
                source=SourceReference(
                    source_kind="route-optimizer-map",
                    source_id="corridor-demand",
                    source_version="1",
                    source_digest=source_digest,
                ),
            ),
        ),
        fleet_options=(fleet,),
        infrastructure_candidates=tuple(candidate_models),
        economic_assumptions=EconomicAssumptions(
            currency="GBP", model_name="bounded-corridor-route", model_version="1"
        ),
        constraints=PlanningConstraints(
            budget_gbp=budget,
            permitted_modes=(Mode.ROAD,),
            # P05 permits station endpoints on a corridor only for a service
            # plan; the same guard keeps two stops from claiming one corridor.
            network_selection=NetworkSelection(
                supplies=(
                    SupplyLimit(
                        origin_id=origin_id,
                        cargo_type=value.cargo_type,
                        quantity=1,
                    ),
                ),
                max_vehicles=1,
                minimum_vehicles_by_demand={"corridor-demand": 1},
            ),
        ),
    )
    tiles_by_location = {
        location.location_id: location.tile.y * value.map_width + location.tile.x
        for location in locations
    }
    return scenario, tiles_by_location


def optimize_corridor_route(value: RouteOptimizerInput) -> OptimizedRoute:
    """Optimize one on-route decision and return its D5-safe geometry."""
    _validated_input(value)
    source_digest = _available_source(value)
    facts = _tile_facts(value)
    candidates = _candidate_routes(value, facts)
    scenario, tiles_by_location = _scenario(value, candidates, source_digest)
    try:
        result = optimize_candidate_network(scenario)
    except OptimizerFailure as error:
        raise RouteOptimizationError(f"route optimizer refused the map: {error}") from error
    validate_execution_plan(result.plan, scenario)
    selected = {
        action.candidate_id: scenario_candidate
        for action in result.plan.infrastructure.actions
        for scenario_candidate in scenario.infrastructure_candidates
        if scenario_candidate.candidate_id == action.candidate_id
    }
    segments = [c for c in selected.values() if c.kind is ConstructionKind.SEGMENT]
    stations = [c for c in selected.values() if c.kind is ConstructionKind.STATION]
    depots = [c for c in selected.values() if c.kind is ConstructionKind.DEPOT]
    if len(segments) != 1 or len(stations) != 2 or len(depots) != 1:
        raise RouteOptimizationError("optimizer decision does not select one bounded corridor")
    segment, depot_candidate = segments[0], depots[0]
    route = tuple(tile.y * value.map_width + tile.x for tile in segment.tiles)
    if not MIN_OPTIMIZED_ROUTE_TILES <= len(route) <= MAX_OPTIMIZED_ROUTE_TILES:
        raise RouteOptimizationError("selected route exceeds the D5 wire bound")
    if len(set(route)) != len(route):
        raise RouteOptimizationError("selected route repeats a tile")
    if any(
        abs(a % value.map_width - b % value.map_width)
        + abs(a // value.map_width - b // value.map_width)
        != 1
        for a, b in zip(route, route[1:], strict=False)
    ):
        raise RouteOptimizationError("selected route is not cardinally contiguous")
    pickup_stations = [
        station
        for station in stations
        if station.site_id is not None and tiles_by_location[station.site_id] == route[0]
    ]
    delivery_stations = [
        station
        for station in stations
        if station.site_id is not None and tiles_by_location[station.site_id] == route[-1]
    ]
    if len(pickup_stations) != 1 or len(delivery_stations) != 1:
        raise RouteOptimizationError("selected stops are not the route endpoints")
    pickup_station, delivery_station = pickup_stations[0], delivery_stations[0]
    if (
        segment.mode is not Mode.ROAD
        or segment.origin_id != pickup_station.site_id
        or (segment.destination_id != delivery_station.site_id)
    ):
        raise RouteOptimizationError("selected segment is not the pickup-to-delivery corridor")
    depot = tiles_by_location[depot_candidate.site_id]
    fronts = [tile for tile in route[1:-1] if _adjacent(depot, {tile}, value.map_width)]
    if len(fronts) != 1:
        raise RouteOptimizationError("selected depot must touch exactly one corridor interior")
    if depot in route:
        raise RouteOptimizationError("selected depot overlaps the corridor")
    expected_id = "corridor-" + hashlib.sha256(",".join(map(str, route)).encode()).hexdigest()[:24]
    if segment.candidate_id != expected_id:
        raise RouteOptimizationError("selected corridor identity does not bind its tiles")
    if not set(route) <= set(value.available_tiles):
        raise RouteOptimizationError("selected route leaves the supplied available tiles")
    return OptimizedRoute(
        scenario=scenario,
        execution_plan=result.plan,
        metrics=result.metrics,
        pickup=route[0],
        pickup_front=route[1],
        delivery=route[-1],
        delivery_front=route[-2],
        depot=depot,
        depot_front=fronts[0],
        route=route,
        candidate_id=segment.candidate_id,
        cargo_type=value.cargo_type,
        cargo_id=value.cargo_id,
        pickup_industry=value.pickup_industry,
        delivery_industry=value.delivery_industry,
    )


def route_from_d5_map(
    *,
    map_width: int,
    map_height: int,
    witness_candidates: tuple[tuple[int, ...], ...],
    pickup: int,
    delivery: int,
    depot: int,
    **kwargs: Any,
) -> OptimizedRoute:
    """Optimize a D5 wiring input expressed as already-surveyed route candidates.

    The D4/D5 staging world is retained as tile facts; this helper turns the
    survey into the same bounded map input the generic optimizer consumes.
    Supplying more than one witness candidate makes the same endpoints compete
    in the production optimizer; supplying one retains the single built route.
    """
    available: set[int] = set()
    for path in witness_candidates:
        if len(path) < MIN_OPTIMIZED_ROUTE_TILES:
            raise RouteOptimizationError("a witness candidate is shorter than a corridor")
        if path[0] != pickup or path[-1] != delivery:
            raise RouteOptimizationError("a witness candidate does not join the supplied endpoints")
        available.update(path)
    available.add(depot)
    available.update((pickup, delivery))
    return optimize_corridor_route(
        RouteOptimizerInput(
            map_width=map_width,
            map_height=map_height,
            available_tiles=tuple(sorted(available)),
            pickup_candidates=(pickup,),
            delivery_candidates=(delivery,),
            depot_candidates=(depot,),
            **kwargs,
        )
    )


def route_from_feasible_tiles(
    *,
    map_width: int,
    map_height: int,
    available_tiles: tuple[int, ...],
    pickup: int,
    delivery: int,
    depot: int,
    **kwargs: Any,
) -> OptimizedRoute:
    """Optimize directly over one source-backed feasible tile set.

    The caller owns the provenance of ``available_tiles``: every tile must be
    an authoritative buildable/connected tile for the scenario.  The optimizer
    discovers every bounded simple corridor in that set, so the same endpoints
    can compete when the supplied feasibility data supports more than one.
    """
    return optimize_corridor_route(
        RouteOptimizerInput(
            map_width=map_width,
            map_height=map_height,
            available_tiles=tuple(sorted(set(available_tiles))),
            pickup_candidates=(pickup,),
            delivery_candidates=(delivery,),
            depot_candidates=(depot,),
            **kwargs,
        )
    )
