"""Prove all advertised v1 choices with P02/P06 public validation, without optimization."""

from decimal import localcontext
from itertools import product

from app.planning.canonical import scenario_hash
from app.planning.domain import (
    CargoAssignment,
    ConstructionAction,
    ConstructionKind,
    ExecutionPlan,
    FleetGroup,
    FleetPlan,
    InfrastructurePlan,
    Mode,
    RoadComposition,
    RoadFleetOption,
    RoutePlan,
    RouteStop,
    StopRole,
    ValidationDeclaration,
)
from app.planning.execution import ExecutionPreparationError, execution_payload
from app.planning.preparation.candidates import eligible
from app.planning.preparation.costs import validate_cost_units
from app.planning.preparation.failures import PreparationFailureCode as Code
from app.planning.preparation.failures import fail
from app.planning.validation import PlanningValidationError


def combination_witnesses(scenario):
    """Structural witnesses only, never winning-network decisions or executable artifacts."""
    if len(scenario.cargo_demands) != 1:
        raise ValueError("P08 v1 requires one demand")
    demand = scenario.cargo_demands[0]
    locations = {s.location_id: s for s in scenario.locations}
    stations = [c for c in scenario.infrastructure_candidates if c.kind is ConstructionKind.STATION]
    depots = [c for c in scenario.infrastructure_candidates if c.kind is ConstructionKind.DEPOT]
    if len(depots) != 1:
        raise ValueError("P08 v1 requires exactly one shared depot")
    segments = [c for c in scenario.infrastructure_candidates if c.kind is ConstructionKind.SEGMENT]
    for a, b, depot, segment, option in product(
        stations, stations, depots, segments, scenario.fleet_options
    ):
        if (
            a.site_id != segment.origin_id
            or b.site_id != segment.destination_id
            or locations[a.site_id].serves_location_id != demand.origin_id
            or locations[b.site_id].serves_location_id != demand.destination_id
        ):
            continue
        if not isinstance(option, RoadFleetOption):
            raise ValueError("nonroad option outside P08 profile")
        # Mirror only P05's selectable compatibility predicates, then validate every witness.
        if (
            demand.cargo_type not in option.vehicle.compatible_cargo_types
            or option.vehicle.capacity_cargo_units == 0
            or option.depot_class != locations[depot.site_id].facility_class
            or option.available_from_day > 0
            or option.available_through_day < 0
        ):
            continue
        selected = (a, b, depot, segment)
        actions = []
        for i, c in enumerate(selected):
            actions.append(
                ConstructionAction(
                    construction_id=f"witness-{i}",
                    candidate_id=c.candidate_id,
                    mode=c.mode,
                    kind=c.kind,
                    depends_on=("witness-0", "witness-1") if i == 3 else (),
                    route_ids=("witness-route",),
                    estimated_build_cost_gbp=c.estimated_build_cost_gbp,
                )
            )
        yield ExecutionPlan(
            schema_version=1,
            plan_id="preparation-witness",
            scenario_id=scenario.scenario_id,
            scenario_version=scenario.scenario_version,
            world_fingerprint=scenario.world_fingerprint,
            planner_name="p08-structural-check",
            planner_version="1",
            strategy_identifier="exhaustive-combinations",
            strategy_version="1",
            planner_inputs_digest=scenario_hash(scenario),
            routes=(
                RoutePlan(
                    route_id="witness-route",
                    mode=Mode.ROAD,
                    path_kind="station_to_station_intent",
                    origin_id=demand.origin_id,
                    destination_id=demand.destination_id,
                    stops=(
                        RouteStop(location_id=a.site_id, role=StopRole.PICKUP),
                        RouteStop(location_id=b.site_id, role=StopRole.DELIVERY),
                        RouteStop(location_id=depot.site_id, role=StopRole.DEPOT),
                    ),
                    cargo_assignments=(
                        CargoAssignment(
                            demand_id=demand.demand_id, quantity=demand.quantity, unit="cargo_units"
                        ),
                    ),
                    fleet_group_id="witness-fleet",
                    infrastructure_ids=tuple(a.construction_id for a in actions),
                ),
            ),
            fleet=FleetPlan(
                groups=(
                    FleetGroup(
                        fleet_group_id="witness-fleet",
                        mode=Mode.ROAD,
                        option_id=option.option_id,
                        count=(demand.quantity + option.vehicle.capacity_cargo_units - 1)
                        // option.vehicle.capacity_cargo_units,
                        route_ids=("witness-route",),
                        demand_ids=(demand.demand_id,),
                        start_day=0,
                        order_mode="repeat_service",
                        planned_trips_per_vehicle=1,
                        composition=RoadComposition(
                            mode=Mode.ROAD, vehicle_type=option.vehicle.vehicle_type
                        ),
                    ),
                )
            ),
            infrastructure=InfrastructurePlan(actions=tuple(actions)),
            validation=ValidationDeclaration(
                validator_version="1",
                supported_modes=(Mode.ROAD,),
                validated_world_fingerprint=scenario.world_fingerprint,
            ),
        )


def check_combination_safety(scenario, bindings, world) -> int:
    """Reject unsafe terrain, terminal orientation, and any P06-invalid selectable choice."""
    source = world.prepared_save_digest
    tiles = {(t.x, t.y): t for t in world.tiles}
    locations = {s.location_id: s for s in scenario.locations}
    try:
        native = {e.engine_id: e for e in world.engines}
        engine_bindings = {e.vehicle_type: e for e in bindings.engines}
        cargo_ids = {c.identifier: c.runtime_id for c in bindings.cargo_ids}
        for option in scenario.fleet_options:
            if not isinstance(option, RoadFleetOption):
                raise ValueError("nonroad fleet")
            binding = engine_bindings[option.vehicle.vehicle_type]
            engine = native[binding.engine_id]
            if (
                engine.articulated
                or engine.refit_required
                or not engine.immediately_buildable
                or not engine.freight
                or engine.default_capacity <= 0
                or option.vehicle.capacity_cargo_units != engine.default_capacity
                or option.vehicle.purchase_cost_gbp != engine.purchase_cost_gbp
                or binding.engine_name != engine.name
                or binding.road_type != engine.road_type
                or engine.road_type != world.profile.road_type
                or option.depot_class != engine.depot_class
                or option.available_from_day != 0
                or option.available_through_day != 0
                or any(
                    cargo_ids[c] != engine.default_cargo_id
                    for c in option.vehicle.compatible_cargo_types
                )
            ):
                raise ValueError("fleet differs from native supported catalog")
        for c in scenario.infrastructure_candidates:
            if c.mode is not Mode.ROAD:
                raise ValueError("nonroad candidate")
            geometry = (
                c.tiles if c.kind is ConstructionKind.SEGMENT else (locations[c.site_id].tile,)
            )
            if any((t.x, t.y) not in tiles or not eligible(tiles[(t.x, t.y)]) for t in geometry):
                raise ValueError("candidate has unsupported terrain")
            if c.kind is ConstructionKind.SEGMENT:
                a, b = locations[c.origin_id], locations[c.destination_id]
                for endpoint, neighbor in ((a, c.tiles[1]), (b, c.tiles[-2])):
                    dx, dy = {"north": (0, -1), "east": (1, 0), "south": (0, 1), "west": (-1, 0)}[
                        endpoint.orientation
                    ]
                    if (neighbor.x, neighbor.y) != (endpoint.tile.x + dx, endpoint.tile.y + dy):
                        raise ValueError("corridor enters station contrary to orientation")
                if any(
                    tiles[(a.x, a.y)].height != tiles[(b.x, b.y)].height
                    for a, b in zip(c.tiles, c.tiles[1:])
                ):
                    raise ValueError("corridor changes elevation")
        count = 0
        purchases = []
        for witness in combination_witnesses(scenario):
            execution_payload(witness, scenario, bindings)
            with localcontext() as context:
                context.prec = 100
                group = witness.fleet.groups[0]
                option = next(o for o in scenario.fleet_options if o.option_id == group.option_id)
                assert isinstance(option, RoadFleetOption)
                purchases.append(option.vehicle.purchase_cost_gbp * group.count)
            count += 1
        if count == 0:
            raise ValueError("no selectable road combination")
        validate_cost_units(
            [c.estimated_build_cost_gbp for c in scenario.infrastructure_candidates] + purchases,
            source,
        )
        return count
    except (
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        PlanningValidationError,
        ExecutionPreparationError,
    ) as error:
        fail(
            Code.INVALID_PREPARATION_OUTPUT,
            "combination-safety",
            source,
            "advertised candidate space violates supported P02/P06 combination rules",
        )
        raise AssertionError("unreachable") from error
