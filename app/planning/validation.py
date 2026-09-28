"""Pure, prelaunch cross-reference validation for planning schema v1."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from pydantic import ValidationError

from app.planning.canonical import world_manifest_hash
from app.planning.domain import (
    CargoDemand,
    ConstructionAction,
    ConstructionKind,
    ExecutionPlan,
    FleetGroup,
    FleetOption,
    InfrastructureCandidate,
    LocationKind,
    PlanningLocation,
    PlanningScenario,
    RailComposition,
    ResolvedSite,
    RoadComposition,
    RoadFleetOption,
    RoutePlan,
    StopRole,
    Tile,
)


class PlanningFailureCode(StrEnum):
    UNSUPPORTED_PLAN_VERSION = "unsupported_plan_version"
    SCENARIO_MISMATCH = "scenario_mismatch"
    INVALID_PLAN = "invalid_plan"
    UNKNOWN_NODE = "unknown_node"
    UNSUPPORTED_MODE = "unsupported_mode"
    INVALID_FLEET = "invalid_fleet"
    UNSUPPORTED_CONSTRUCTION = "unsupported_construction"


class PlanningValidationError(ValueError):
    def __init__(self, code: PlanningFailureCode, detail: str) -> None:
        self.code = code
        super().__init__(detail)


def _require(condition: bool, code: PlanningFailureCode, detail: str) -> None:
    if not condition:
        raise PlanningValidationError(code, detail)


def _unique(values: list[str], kind: str) -> None:
    _require(len(values) == len(set(values)), PlanningFailureCode.INVALID_PLAN, f"duplicate {kind}")


@dataclass(frozen=True)
class _Index:
    locations: dict[str, PlanningLocation]
    demands: dict[str, CargoDemand]
    options: dict[str, FleetOption]
    candidates: dict[str, InfrastructureCandidate]
    routes: dict[str, RoutePlan]
    groups: dict[str, FleetGroup]
    actions: dict[str, ConstructionAction]


def validate_execution_plan(plan: ExecutionPlan, scenario: PlanningScenario) -> None:
    """Validate typed decisions against the same scenario snapshot before launch.

    This cannot prove actual OpenTTD construction succeeds. P03 must compare the
    world fingerprint with a prepared world's independent evidence.
    """
    _require(
        plan.schema_version == 1 and scenario.schema_version == 1,
        PlanningFailureCode.UNSUPPORTED_PLAN_VERSION,
        "unsupported planning schema",
    )
    # model_copy(update=...) bypasses Pydantic validation. Reparse even typed
    # inputs so this public prelaunch boundary cannot be bypassed that way.
    try:
        plan = ExecutionPlan.model_validate_json(plan.model_dump_json())
        scenario = PlanningScenario.model_validate_json(scenario.model_dump_json())
    except (ValidationError, ValueError) as exc:
        raise PlanningValidationError(
            PlanningFailureCode.INVALID_PLAN, "invalid typed planning contract"
        ) from exc
    _require(
        (plan.scenario_id, plan.scenario_version, plan.world_fingerprint)
        == (scenario.scenario_id, scenario.scenario_version, scenario.world_fingerprint)
        and plan.validation.validated_world_fingerprint == scenario.world_fingerprint,
        PlanningFailureCode.SCENARIO_MISMATCH,
        "plan and scenario identity differ",
    )
    manifest = scenario.world_manifest
    _require(
        manifest.width_tiles == scenario.width_tiles
        and manifest.height_tiles == scenario.height_tiles
        and manifest.seed == scenario.seed
        and manifest.openttd_version == scenario.openttd_version
        and manifest.base_set_name == scenario.base_set_name
        and manifest.base_set_version == scenario.base_set_version
        and world_manifest_hash(manifest) == scenario.world_fingerprint,
        PlanningFailureCode.SCENARIO_MISMATCH,
        "world manifest digest or generation identity differs",
    )
    sites = {site.location_id: site for site in manifest.resolved_sites}
    _require(
        len(sites) == len(manifest.resolved_sites),
        PlanningFailureCode.INVALID_PLAN,
        "duplicate resolved site",
    )
    for name, values in (
        ("cargo type", manifest.cargo_types),
        ("vehicle type", manifest.vehicle_types),
    ):
        _unique(list(values), name)
    _require(
        len(manifest.buildable_tiles) == len(set(manifest.buildable_tiles)),
        PlanningFailureCode.INVALID_PLAN,
        "duplicate buildable tile",
    )
    locations = {item.location_id: item for item in scenario.locations}
    demands = {item.demand_id: item for item in scenario.cargo_demands}
    options = {item.option_id: item for item in scenario.fleet_options}
    candidates = {item.candidate_id: item for item in scenario.infrastructure_candidates}
    routes = {item.route_id: item for item in plan.routes}
    groups = {item.fleet_group_id: item for item in plan.fleet.groups}
    actions = {item.construction_id: item for item in plan.infrastructure.actions}
    index = _Index(locations, demands, options, candidates, routes, groups, actions)
    for label, items, ids in (
        ("location", scenario.locations, locations),
        ("demand", scenario.cargo_demands, demands),
        ("fleet option", scenario.fleet_options, options),
        ("infrastructure candidate", scenario.infrastructure_candidates, candidates),
        ("route", plan.routes, routes),
        ("fleet group", plan.fleet.groups, groups),
        ("construction action", plan.infrastructure.actions, actions),
    ):
        _require(len(items) == len(ids), PlanningFailureCode.INVALID_PLAN, f"duplicate {label}")
    _unique([str(mode) for mode in scenario.supported_modes], "supported mode")
    _unique([str(mode) for mode in scenario.constraints.permitted_modes], "permitted mode")
    _unique([str(mode) for mode in plan.validation.supported_modes], "validator mode")
    _require(
        set(scenario.constraints.permitted_modes) <= set(scenario.supported_modes)
        and set(plan.validation.supported_modes) <= set(scenario.supported_modes),
        PlanningFailureCode.UNSUPPORTED_MODE,
        "mode declaration exceeds scenario support",
    )

    _validate_scenario(scenario, index, sites)
    _validate_routes(plan, scenario, index)
    planned_capex = _validate_fleet(plan, scenario, index)
    _validate_infrastructure(plan, index)
    if scenario.constraints.budget_gbp is not None:
        _require(
            planned_capex <= scenario.constraints.budget_gbp,
            PlanningFailureCode.INVALID_PLAN,
            "planned construction and fleet purchases exceed budget",
        )


def _validate_scenario(
    scenario: PlanningScenario, index: _Index, sites: dict[str, ResolvedSite]
) -> None:
    manifest = scenario.world_manifest
    locations = index.locations
    for location in scenario.locations:
        _require(
            location.location_id in sites,
            PlanningFailureCode.UNKNOWN_NODE,
            "location unresolved in world manifest",
        )
        site = sites[location.location_id]
        _require(
            location.tile == site.tile
            and location.kind == site.kind
            and set(location.permitted_modes) == set(site.permitted_modes)
            and location.serves_location_id == site.serves_location_id
            and location.footprint_width_tiles == site.footprint_width_tiles
            and location.footprint_height_tiles == site.footprint_height_tiles
            and location.orientation == site.orientation
            and location.platform_length_tiles == site.platform_length_tiles
            and location.facility_class == site.facility_class,
            PlanningFailureCode.SCENARIO_MISMATCH,
            "planning location differs from prepared site",
        )
        _require(
            location.tile.x < scenario.width_tiles and location.tile.y < scenario.height_tiles,
            PlanningFailureCode.UNKNOWN_NODE,
            "location tile outside map",
        )
        if location.world_reference is not None:
            _require(
                location.world_reference.world_fingerprint == scenario.world_fingerprint,
                PlanningFailureCode.SCENARIO_MISMATCH,
                "world reference differs",
            )
            _require(
                location.world_reference.kind == site.world_kind
                and location.world_reference.world_id == site.world_id,
                PlanningFailureCode.SCENARIO_MISMATCH,
                "world entity differs from prepared site",
            )
        if location.serves_location_id is not None:
            _require(
                location.kind is LocationKind.STATION_CANDIDATE
                and location.serves_location_id in locations
                and locations[location.serves_location_id].kind
                in {LocationKind.INDUSTRY_ORIGIN, LocationKind.INDUSTRY_DESTINATION},
                PlanningFailureCode.UNKNOWN_NODE,
                "station service location invalid",
            )
        _require(
            set(location.permitted_modes) <= set(scenario.supported_modes),
            PlanningFailureCode.UNSUPPORTED_MODE,
            "location has unsupported mode",
        )
        if location.footprint_width_tiles is not None:
            _require(
                location.tile.x + location.footprint_width_tiles <= scenario.width_tiles,
                PlanningFailureCode.UNKNOWN_NODE,
                "site footprint outside map",
            )
        if location.footprint_height_tiles is not None:
            _require(
                location.tile.y + location.footprint_height_tiles <= scenario.height_tiles,
                PlanningFailureCode.UNKNOWN_NODE,
                "site footprint outside map",
            )
    for demand in scenario.cargo_demands:
        _require(
            demand.cargo_type in manifest.cargo_types,
            PlanningFailureCode.INVALID_PLAN,
            "cargo type unresolved in world manifest",
        )
        _require(
            demand.origin_id in locations and demand.destination_id in locations,
            PlanningFailureCode.UNKNOWN_NODE,
            "demand node missing",
        )
        _require(
            demand.origin_id != demand.destination_id
            and demand.earliest_day <= demand.latest_delivery_day < scenario.horizon_days,
            PlanningFailureCode.INVALID_PLAN,
            "invalid demand endpoints or horizon",
        )
    for option in scenario.fleet_options:
        _require(
            option.mode in scenario.supported_modes
            and option.available_from_day <= option.available_through_day,
            PlanningFailureCode.INVALID_FLEET,
            "fleet option mode or availability invalid",
        )
        if isinstance(option, RoadFleetOption):
            _require(
                option.vehicle.capacity_cargo_units > 0
                and option.vehicle.vehicle_type in manifest.vehicle_types
                and bool(option.vehicle.compatible_cargo_types),
                PlanningFailureCode.INVALID_FLEET,
                "road vehicle lacks cargo capacity",
            )
        else:
            _unique([wagon.vehicle_type for wagon in option.wagon_options], "wagon option")
            _require(
                option.locomotive.length_tiles is not None
                and option.locomotive.vehicle_type in manifest.vehicle_types
                and all(
                    wagon.length_tiles is not None
                    and wagon.capacity_cargo_units > 0
                    and wagon.compatible_cargo_types
                    and wagon.vehicle_type in manifest.vehicle_types
                    for wagon in option.wagon_options
                ),
                PlanningFailureCode.INVALID_FLEET,
                "rail option lacks wagon capacity or length",
            )
    for candidate in scenario.infrastructure_candidates:
        _require(
            candidate.mode in scenario.supported_modes,
            PlanningFailureCode.UNSUPPORTED_MODE,
            "candidate mode unsupported",
        )
        if candidate.kind is ConstructionKind.SEGMENT:
            _require(
                candidate.site_id is None
                and candidate.origin_id in locations
                and candidate.destination_id in locations
                and candidate.origin_id != candidate.destination_id
                and len(candidate.tiles) >= 2,
                PlanningFailureCode.UNSUPPORTED_CONSTRUCTION,
                "segment needs endpoints and explicit tile sequence",
            )
            if candidate.origin_id is None or candidate.destination_id is None:
                raise PlanningValidationError(
                    PlanningFailureCode.UNSUPPORTED_CONSTRUCTION, "segment endpoints missing"
                )
            _require(
                all(
                    0 <= tile.x < scenario.width_tiles
                    and 0 <= tile.y < scenario.height_tiles
                    and tile in manifest.buildable_tiles
                    for tile in candidate.tiles
                ),
                PlanningFailureCode.UNSUPPORTED_CONSTRUCTION,
                "segment tile outside map",
            )
            _require(
                all(
                    max(abs(a.x - b.x), abs(a.y - b.y)) == 1
                    for a, b in zip(candidate.tiles, candidate.tiles[1:], strict=False)
                ),
                PlanningFailureCode.UNSUPPORTED_CONSTRUCTION,
                "segment tile sequence is not contiguous",
            )
            _require(
                candidate.tiles[0] == locations[candidate.origin_id].tile
                and candidate.tiles[-1] == locations[candidate.destination_id].tile
                and candidate.mode in locations[candidate.origin_id].permitted_modes
                and candidate.mode in locations[candidate.destination_id].permitted_modes,
                PlanningFailureCode.UNSUPPORTED_CONSTRUCTION,
                "segment does not connect compatible endpoint sites",
            )
        else:
            _require(
                candidate.site_id in locations
                and candidate.origin_id is None
                and candidate.destination_id is None
                and not candidate.tiles
                and locations[candidate.site_id].kind
                is (
                    LocationKind.STATION_CANDIDATE
                    if candidate.kind is ConstructionKind.STATION
                    else LocationKind.DEPOT_CANDIDATE
                ),
                PlanningFailureCode.UNSUPPORTED_CONSTRUCTION,
                "station/depot candidate needs compatible site",
            )
            if candidate.site_id is None:
                raise PlanningValidationError(
                    PlanningFailureCode.UNSUPPORTED_CONSTRUCTION, "construction site missing"
                )
            _require(
                candidate.mode in locations[candidate.site_id].permitted_modes,
                PlanningFailureCode.UNSUPPORTED_MODE,
                "construction site mode differs",
            )
            _require(
                locations[candidate.site_id].tile in manifest.buildable_tiles,
                PlanningFailureCode.UNSUPPORTED_CONSTRUCTION,
                "site tile not buildable in world manifest",
            )


def _validate_routes(plan: ExecutionPlan, scenario: PlanningScenario, index: _Index) -> None:
    locations, demands = index.locations, index.demands
    groups, actions, candidates = index.groups, index.actions, index.candidates
    assigned: dict[str, int] = {}
    for route in plan.routes:
        _require(
            route.mode in scenario.supported_modes
            and route.mode in scenario.constraints.permitted_modes
            and route.mode in plan.validation.supported_modes,
            PlanningFailureCode.UNSUPPORTED_MODE,
            "route mode not supported",
        )
        _require(
            route.origin_id in locations
            and route.destination_id in locations
            and all(stop.location_id in locations for stop in route.stops),
            PlanningFailureCode.UNKNOWN_NODE,
            "route node missing",
        )
        _require(
            route.origin_id != route.destination_id
            and locations[route.stops[0].location_id].serves_location_id == route.origin_id
            and route.stops[0].role is StopRole.PICKUP
            and locations[route.stops[-2].location_id].serves_location_id == route.destination_id
            and route.stops[-2].role is StopRole.DELIVERY
            and route.stops[-1].role is StopRole.DEPOT
            and locations[route.stops[-1].location_id].kind is LocationKind.DEPOT_CANDIDATE
            and all(
                stop.role is StopRole.SERVICE
                and locations[stop.location_id].kind is LocationKind.SERVICE_WAYPOINT
                for stop in route.stops[1:-2]
            )
            and all(
                route.mode in locations[stop.location_id].permitted_modes for stop in route.stops
            ),
            PlanningFailureCode.INVALID_PLAN,
            "route stops or endpoints invalid",
        )
        _require(
            route.fleet_group_id in groups,
            PlanningFailureCode.INVALID_FLEET,
            "route fleet group missing",
        )
        _unique(list(route.infrastructure_ids), "route infrastructure reference")
        _unique([item.demand_id for item in route.cargo_assignments], "route demand assignment")
        for assignment in route.cargo_assignments:
            _require(
                assignment.demand_id in demands,
                PlanningFailureCode.INVALID_PLAN,
                "route demand missing",
            )
            demand = demands[assignment.demand_id]
            _require(
                assignment.unit == demand.unit
                and route.origin_id == demand.origin_id
                and route.destination_id == demand.destination_id,
                PlanningFailureCode.INVALID_PLAN,
                "route cargo endpoints or units differ",
            )
            assigned[assignment.demand_id] = (
                assigned.get(assignment.demand_id, 0) + assignment.quantity
            )
        for action_id in route.infrastructure_ids:
            _require(
                action_id in actions
                and actions[action_id].candidate_id in candidates
                and route.route_id in actions[action_id].route_ids,
                PlanningFailureCode.INVALID_PLAN,
                "route infrastructure reference missing",
            )
    _require(
        all(quantity <= demands[demand_id].quantity for demand_id, quantity in assigned.items()),
        PlanningFailureCode.INVALID_PLAN,
        "assigned cargo exceeds demand",
    )


def _validate_fleet(plan: ExecutionPlan, scenario: PlanningScenario, index: _Index) -> Decimal:
    locations, demands, options = index.locations, index.demands, index.options
    candidates, routes, actions = index.candidates, index.routes, index.actions
    planned_capex = sum(
        (action.estimated_build_cost_gbp for action in plan.infrastructure.actions),
        start=Decimal("0"),
    )
    for group in plan.fleet.groups:
        _require(
            group.option_id in options, PlanningFailureCode.INVALID_FLEET, "fleet option missing"
        )
        option = options[group.option_id]
        _require(
            group.mode == option.mode
            and group.mode == group.composition.mode
            and option.available_from_day <= group.start_day <= option.available_through_day
            and group.start_day < scenario.horizon_days,
            PlanningFailureCode.INVALID_FLEET,
            "fleet mode or availability differs",
        )
        _unique(list(group.route_ids), "fleet route reference")
        _unique(list(group.demand_ids), "fleet demand reference")
        _require(
            all(
                route_id in routes
                and routes[route_id].fleet_group_id == group.fleet_group_id
                and routes[route_id].mode == group.mode
                for route_id in group.route_ids
            ),
            PlanningFailureCode.INVALID_FLEET,
            "fleet route reference invalid",
        )
        _require(
            set(group.route_ids)
            == {
                route.route_id
                for route in plan.routes
                if route.fleet_group_id == group.fleet_group_id
            },
            PlanningFailureCode.INVALID_FLEET,
            "fleet route assignments differ",
        )
        cargo_ids = {
            item.demand_id
            for route_id in group.route_ids
            for item in routes[route_id].cargo_assignments
        }
        _require(
            set(group.demand_ids) == cargo_ids,
            PlanningFailureCode.INVALID_FLEET,
            "fleet cargo assignments differ",
        )
        cargo_types = {demands[demand_id].cargo_type for demand_id in cargo_ids}
        assigned_quantity = sum(
            item.quantity
            for route_id in group.route_ids
            for item in routes[route_id].cargo_assignments
        )
        if isinstance(option, RoadFleetOption):
            _require(
                isinstance(group.composition, RoadComposition)
                and group.composition.vehicle_type == option.vehicle.vehicle_type
                and cargo_types <= set(option.vehicle.compatible_cargo_types),
                PlanningFailureCode.INVALID_FLEET,
                "road composition or cargo incompatible",
            )
            _require(
                any(
                    candidate.kind is ConstructionKind.DEPOT
                    and candidate.site_id is not None
                    and locations[candidate.site_id].facility_class == option.depot_class
                    for route_id in group.route_ids
                    for action_id in routes[route_id].infrastructure_ids
                    for candidate in (candidates[actions[action_id].candidate_id],)
                ),
                PlanningFailureCode.INVALID_FLEET,
                "road fleet has no compatible depot",
            )
            planned_capex += option.vehicle.purchase_cost_gbp * group.count
            _require(
                assigned_quantity
                <= option.vehicle.capacity_cargo_units
                * group.count
                * group.planned_trips_per_vehicle,
                PlanningFailureCode.INVALID_FLEET,
                "road service capacity below assignment",
            )
        else:
            if not isinstance(group.composition, RailComposition):
                raise PlanningValidationError(
                    PlanningFailureCode.INVALID_FLEET, "rail composition required"
                )
            consist = group.composition
            wagon_options = {wagon.vehicle_type: wagon for wagon in option.wagon_options}
            _unique([wagon.wagon_type for wagon in consist.wagons], "chosen wagon")
            _require(
                consist.locomotive_type == option.locomotive.vehicle_type
                and all(wagon.wagon_type in wagon_options for wagon in consist.wagons),
                PlanningFailureCode.INVALID_FLEET,
                "rail vehicle choice invalid",
            )
            capacity = sum(
                wagon_options[w.wagon_type].capacity_cargo_units * w.count for w in consist.wagons
            )
            length = (option.locomotive.length_tiles or 0) + sum(
                (wagon_options[w.wagon_type].length_tiles or 0) * w.count for w in consist.wagons
            )
            _require(
                consist.total_capacity_cargo_units == capacity
                and consist.total_length_tiles == length
                and length <= option.max_train_length_tiles
                and (
                    scenario.constraints.max_train_length_tiles is None
                    or length <= scenario.constraints.max_train_length_tiles
                )
                and all(
                    any(
                        cargo in wagon_options[w.wagon_type].compatible_cargo_types
                        for w in consist.wagons
                    )
                    for cargo in cargo_types
                ),
                PlanningFailureCode.INVALID_FLEET,
                "rail capacity, length or cargo invalid",
            )
            _require(
                assigned_quantity <= capacity * group.count * group.planned_trips_per_vehicle,
                PlanningFailureCode.INVALID_FLEET,
                "rail service capacity below assignment",
            )
            for cargo_type in cargo_types:
                cargo_quantity = sum(
                    item.quantity
                    for route_id in group.route_ids
                    for item in routes[route_id].cargo_assignments
                    if demands[item.demand_id].cargo_type == cargo_type
                )
                compatible_capacity = sum(
                    wagon_options[w.wagon_type].capacity_cargo_units * w.count
                    for w in consist.wagons
                    if cargo_type in wagon_options[w.wagon_type].compatible_cargo_types
                )
                _require(
                    cargo_quantity
                    <= compatible_capacity * group.count * group.planned_trips_per_vehicle,
                    PlanningFailureCode.INVALID_FLEET,
                    "rail cargo exceeds compatible wagon capacity",
                )
            planned_capex += (
                option.locomotive.purchase_cost_gbp
                + sum(
                    wagon_options[w.wagon_type].purchase_cost_gbp * w.count for w in consist.wagons
                )
            ) * group.count
            for route_id in group.route_ids:
                for action_id in routes[route_id].infrastructure_ids:
                    candidate = candidates[actions[action_id].candidate_id]
                    if candidate.kind is ConstructionKind.SEGMENT:
                        _require(
                            candidate.rail_type == option.rail_type,
                            PlanningFailureCode.INVALID_FLEET,
                            "rail type differs",
                        )
                    if candidate.kind is ConstructionKind.STATION:
                        if candidate.site_id is None:
                            raise PlanningValidationError(
                                PlanningFailureCode.UNSUPPORTED_CONSTRUCTION,
                                "station site missing",
                            )
                        site = locations[candidate.site_id]
                        _require(
                            site.platform_length_tiles is not None
                            and length <= site.platform_length_tiles,
                            PlanningFailureCode.INVALID_FLEET,
                            "consist exceeds station platform",
                        )
    return planned_capex


def _validate_infrastructure(plan: ExecutionPlan, index: _Index) -> None:
    locations, candidates, routes, actions = (
        index.locations,
        index.candidates,
        index.routes,
        index.actions,
    )
    seen: set[str] = set()
    selected_candidates: set[str] = set()
    occupied_sites: set[Tile] = set()
    segment_tiles: set[Tile] = set()
    depot_tiles: set[Tile] = set()
    for action in plan.infrastructure.actions:
        _require(
            action.candidate_id in candidates,
            PlanningFailureCode.UNSUPPORTED_CONSTRUCTION,
            "construction candidate missing",
        )
        candidate = candidates[action.candidate_id]
        _require(
            candidate.candidate_id not in selected_candidates,
            PlanningFailureCode.UNSUPPORTED_CONSTRUCTION,
            "infrastructure candidate built twice",
        )
        selected_candidates.add(candidate.candidate_id)
        _require(
            action.mode == candidate.mode and action.kind == candidate.kind,
            PlanningFailureCode.UNSUPPORTED_CONSTRUCTION,
            "construction differs from candidate",
        )
        _require(
            action.estimated_build_cost_gbp == candidate.estimated_build_cost_gbp,
            PlanningFailureCode.UNSUPPORTED_CONSTRUCTION,
            "construction estimate differs from catalog",
        )
        _unique(list(action.depends_on), "construction dependency")
        _unique(list(action.route_ids), "construction route")
        _require(
            all(dependency in seen for dependency in action.depends_on),
            PlanningFailureCode.UNSUPPORTED_CONSTRUCTION,
            "construction dependencies must precede action",
        )
        _require(
            all(
                route_id in routes
                and routes[route_id].mode == action.mode
                and action.construction_id in routes[route_id].infrastructure_ids
                for route_id in action.route_ids
            ),
            PlanningFailureCode.UNSUPPORTED_CONSTRUCTION,
            "construction route users invalid",
        )
        if candidate.kind is ConstructionKind.SEGMENT:
            tiles = set(candidate.tiles)
            _require(
                not tiles.intersection(segment_tiles),
                PlanningFailureCode.UNSUPPORTED_CONSTRUCTION,
                "construction corridors overlap",
            )
            segment_tiles.update(tiles)
        elif candidate.site_id is not None:
            site = locations[candidate.site_id]
            footprint = {
                Tile(x=x, y=y)
                for x in range(site.tile.x, site.tile.x + (candidate.footprint_width_tiles or 1))
                for y in range(site.tile.y, site.tile.y + (candidate.footprint_height_tiles or 1))
            }
            _require(
                not footprint.intersection(occupied_sites),
                PlanningFailureCode.UNSUPPORTED_CONSTRUCTION,
                "construction sites overlap",
            )
            occupied_sites.update(footprint)
            if candidate.kind is ConstructionKind.DEPOT:
                depot_tiles.update(footprint)
        seen.add(action.construction_id)
    _require(
        not depot_tiles.intersection(segment_tiles),
        PlanningFailureCode.UNSUPPORTED_CONSTRUCTION,
        "depot and corridor tiles overlap",
    )
    for route in plan.routes:
        kinds = {actions[action_id].kind for action_id in route.infrastructure_ids}
        _require(
            {ConstructionKind.STATION, ConstructionKind.DEPOT, ConstructionKind.SEGMENT} <= kinds,
            PlanningFailureCode.UNSUPPORTED_CONSTRUCTION,
            "route needs stations, depot, and segment",
        )
        _require(
            all(actions[action_id].mode == route.mode for action_id in route.infrastructure_ids),
            PlanningFailureCode.UNSUPPORTED_MODE,
            "route infrastructure mode differs",
        )
        route_candidates = [
            candidates[actions[action_id].candidate_id] for action_id in route.infrastructure_ids
        ]
        station_sites = {
            candidate.site_id
            for candidate in route_candidates
            if candidate.kind is ConstructionKind.STATION
        }
        _require(
            route.stops[0].location_id in station_sites
            and route.stops[-2].location_id in station_sites
            and any(
                candidate.kind is ConstructionKind.DEPOT
                and candidate.site_id == route.stops[-1].location_id
                for candidate in route_candidates
            )
            and any(
                candidate.kind is ConstructionKind.SEGMENT
                and candidate.origin_id == route.stops[0].location_id
                and candidate.destination_id == route.stops[-2].location_id
                for candidate in route_candidates
            ),
            PlanningFailureCode.UNSUPPORTED_CONSTRUCTION,
            "route stations and corridor are not connected",
        )
