"""Small, pinned contract fixtures; no OpenTTD process or world is created."""

import json
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.planning.domain import (
    CargoAssignment,
    CargoDemand,
    ConstructionAction,
    ConstructionKind,
    EconomicAssumptions,
    EstimatedPlanMetrics,
    ExecutionPlan,
    FleetGroup,
    FleetPlan,
    InfrastructureCandidate,
    InfrastructurePlan,
    LocationKind,
    Mode,
    PlanningConstraints,
    PlanningLocation,
    PlanningScenario,
    PreparedWorldManifest,
    RailComposition,
    RailFleetOption,
    ResolvedSite,
    RoadComposition,
    RoadFleetOption,
    RoutePlan,
    RouteStop,
    SourceReference,
    StopRole,
    Tile,
    ValidationDeclaration,
    VehicleDefinition,
    WagonComposition,
)
from app.planning.serialization import (
    canonical_bytes,
    load_plan_artifact,
    plan_artifact_bytes,
    plan_hash,
    scenario_hash,
    verify_plan_hash,
    world_manifest_hash,
)
from app.planning.validation import (
    PlanningFailureCode,
    PlanningValidationError,
    validate_execution_plan,
)

SOURCE = SourceReference(source_kind="fixture", source_id="tiny-map", source_version="1")


def _manifest() -> PreparedWorldManifest:
    sites = [
        ResolvedSite(
            location_id="origin",
            tile=Tile(x=4, y=4),
            kind=LocationKind.INDUSTRY_ORIGIN,
            permitted_modes=(Mode.ROAD, Mode.RAIL),
        ),
        ResolvedSite(
            location_id="destination",
            tile=Tile(x=20, y=4),
            kind=LocationKind.INDUSTRY_DESTINATION,
            permitted_modes=(Mode.ROAD, Mode.RAIL),
        ),
    ]
    for mode, y in ((Mode.ROAD, 4), (Mode.RAIL, 8)):
        sites.extend(
            (
                ResolvedSite(
                    location_id=f"{mode}-station-a",
                    tile=Tile(x=5, y=y),
                    kind=LocationKind.STATION_CANDIDATE,
                    permitted_modes=(mode,),
                    serves_location_id="origin",
                    platform_length_tiles=10 if mode is Mode.RAIL else None,
                ),
                ResolvedSite(
                    location_id=f"{mode}-station-b",
                    tile=Tile(x=19, y=y),
                    kind=LocationKind.STATION_CANDIDATE,
                    permitted_modes=(mode,),
                    serves_location_id="destination",
                    platform_length_tiles=10 if mode is Mode.RAIL else None,
                ),
                ResolvedSite(
                    location_id=f"{mode}-depot",
                    tile=Tile(x=5, y=y + 1),
                    kind=LocationKind.DEPOT_CANDIDATE,
                    permitted_modes=(mode,),
                    facility_class="road" if mode is Mode.ROAD else "rail",
                ),
            )
        )
    return PreparedWorldManifest(
        schema_version=1,
        source_digest="d" * 64,
        openttd_version="13.4",
        base_set_name="OpenGFX",
        base_set_version="7.1",
        width_tiles=64,
        height_tiles=64,
        seed=17,
        resolved_sites=tuple(sites),
        cargo_types=("COAL",),
        vehicle_types=("lorry", "engine", "wagon"),
        buildable_tiles=tuple(Tile(x=x, y=y) for y in (4, 8) for x in range(5, 20))
        + (Tile(x=5, y=5), Tile(x=5, y=9)),
    )


FINGERPRINT = world_manifest_hash(_manifest())


def _vehicle(name: str, capacity: int, length: int | None = None) -> VehicleDefinition:
    return VehicleDefinition(
        vehicle_type=name,
        capacity_cargo_units=capacity,
        purchase_cost_gbp="100",
        running_cost_gbp_per_day="2",
        speed_km_per_hour="40",
        length_tiles=length,
        compatible_cargo_types=("COAL",),
    )


def tiny_scenario() -> PlanningScenario:
    locations = [
        PlanningLocation(
            location_id="origin",
            tile=Tile(x=4, y=4),
            kind=LocationKind.INDUSTRY_ORIGIN,
            permitted_modes=(Mode.ROAD, Mode.RAIL),
        ),
        PlanningLocation(
            location_id="destination",
            tile=Tile(x=20, y=4),
            kind=LocationKind.INDUSTRY_DESTINATION,
            permitted_modes=(Mode.ROAD, Mode.RAIL),
        ),
    ]
    candidates = []
    for mode, y in ((Mode.ROAD, 4), (Mode.RAIL, 8)):
        for suffix, x, serves in (("a", 5, "origin"), ("b", 19, "destination")):
            site = f"{mode}-station-{suffix}"
            locations.append(
                PlanningLocation(
                    location_id=site,
                    tile=Tile(x=x, y=y),
                    kind=LocationKind.STATION_CANDIDATE,
                    permitted_modes=(mode,),
                    serves_location_id=serves,
                    platform_length_tiles=10 if mode is Mode.RAIL else None,
                )
            )
            candidates.append(
                InfrastructureCandidate(
                    candidate_id=site,
                    mode=mode,
                    kind=ConstructionKind.STATION,
                    site_id=site,
                    estimated_build_cost_gbp="25",
                    source=SOURCE,
                )
            )
        depot = f"{mode}-depot"
        locations.append(
            PlanningLocation(
                location_id=depot,
                tile=Tile(x=5, y=y + 1),
                kind=LocationKind.DEPOT_CANDIDATE,
                permitted_modes=(mode,),
                facility_class="road" if mode is Mode.ROAD else "rail",
            )
        )
        candidates.append(
            InfrastructureCandidate(
                candidate_id=depot,
                mode=mode,
                kind=ConstructionKind.DEPOT,
                site_id=depot,
                estimated_build_cost_gbp="20",
                source=SOURCE,
            )
        )
        candidates.append(
            InfrastructureCandidate(
                candidate_id=f"{mode}-segment",
                mode=mode,
                kind=ConstructionKind.SEGMENT,
                origin_id=f"{mode}-station-a",
                destination_id=f"{mode}-station-b",
                tiles=tuple(Tile(x=x, y=y) for x in range(5, 20)),
                rail_type="rail" if mode is Mode.RAIL else None,
                estimated_build_cost_gbp="200",
                source=SOURCE,
            )
        )
    return PlanningScenario(
        schema_version=1,
        scenario_id="tiny",
        scenario_version="1",
        world_fingerprint=FINGERPRINT,
        world_manifest=_manifest(),
        openttd_version="13.4",
        base_set_name="OpenGFX",
        base_set_version="7.1",
        width_tiles=64,
        height_tiles=64,
        seed=17,
        start_date=date(1950, 1, 1),
        horizon_days=120,
        supported_modes=(Mode.ROAD, Mode.RAIL),
        locations=tuple(locations),
        cargo_demands=(
            CargoDemand(
                demand_id="coal-flow",
                cargo_type="COAL",
                origin_id="origin",
                destination_id="destination",
                quantity=100,
                unit="cargo_units",
                earliest_day=0,
                latest_delivery_day=119,
                source=SOURCE,
            ),
        ),
        fleet_options=(
            RoadFleetOption(
                option_id="road-option",
                mode=Mode.ROAD,
                vehicle=_vehicle("lorry", 20),
                road_vehicle_class="lorry",
                depot_class="road",
                available_from_day=0,
                available_through_day=119,
                source=SOURCE,
            ),
            RailFleetOption(
                option_id="rail-option",
                mode=Mode.RAIL,
                locomotive=_vehicle("engine", 0, 2),
                wagon_options=(_vehicle("wagon", 30, 1),),
                rail_type="rail",
                max_train_length_tiles=8,
                available_from_day=0,
                available_through_day=119,
                source=SOURCE,
            ),
        ),
        infrastructure_candidates=tuple(candidates),
        economic_assumptions=EconomicAssumptions(
            currency="GBP",
            model_name="fixture",
            model_version="1",
            revenue_gbp_per_cargo_unit="2.00",
        ),
        constraints=PlanningConstraints(
            permitted_modes=(Mode.ROAD, Mode.RAIL), budget_gbp="10000", max_train_length_tiles=8
        ),
    )


def tiny_plan(mode: Mode = Mode.ROAD) -> ExecutionPlan:
    prefix = str(mode)
    route_id = f"{prefix}-route"
    group_id = f"{prefix}-group"
    ids = (f"{prefix}-station-a", f"{prefix}-station-b", f"{prefix}-depot", f"{prefix}-segment")
    route = RoutePlan(
        route_id=route_id,
        mode=mode,
        path_kind="station_to_station_intent",
        origin_id="origin",
        destination_id="destination",
        stops=(
            RouteStop(location_id=ids[0], role=StopRole.PICKUP),
            RouteStop(location_id=ids[1], role=StopRole.DELIVERY),
            RouteStop(location_id=ids[2], role=StopRole.DEPOT),
        ),
        cargo_assignments=(
            CargoAssignment(demand_id="coal-flow", quantity=60, unit="cargo_units"),
        ),
        fleet_group_id=group_id,
        infrastructure_ids=tuple(sorted(ids)),
    )
    composition = (
        RoadComposition(mode=Mode.ROAD, vehicle_type="lorry")
        if mode is Mode.ROAD
        else RailComposition(
            mode=Mode.RAIL,
            locomotive_type="engine",
            wagons=(WagonComposition(wagon_type="wagon", count=2),),
            total_capacity_cargo_units=60,
            total_length_tiles=4,
        )
    )
    fleet = FleetPlan(
        groups=(
            FleetGroup(
                fleet_group_id=group_id,
                mode=mode,
                option_id=f"{prefix}-option",
                count=1,
                route_ids=(route_id,),
                demand_ids=("coal-flow",),
                start_day=0,
                order_mode="repeat_service",
                planned_trips_per_vehicle=3 if mode is Mode.ROAD else 1,
                composition=composition,
            ),
        )
    )
    actions = tuple(
        ConstructionAction(
            construction_id=identifier,
            candidate_id=identifier,
            mode=mode,
            kind=(
                ConstructionKind.STATION
                if "station" in identifier
                else ConstructionKind.DEPOT
                if "depot" in identifier
                else ConstructionKind.SEGMENT
            ),
            route_ids=(route_id,),
            estimated_build_cost_gbp="200"
            if "segment" in identifier
            else "20"
            if "depot" in identifier
            else "25",
        )
        for identifier in ids
    )
    return ExecutionPlan(
        schema_version=1,
        plan_id=f"{prefix}-plan",
        scenario_id="tiny",
        scenario_version="1",
        world_fingerprint=FINGERPRINT,
        planner_name="fixture",
        planner_version="1",
        strategy_identifier="fixture",
        strategy_version="1",
        planner_inputs_digest="b" * 64,
        routes=(route,),
        fleet=fleet,
        infrastructure=InfrastructurePlan(actions=actions),
        validation=ValidationDeclaration(
            validator_version="1",
            supported_modes=(Mode.RAIL, Mode.ROAD),
            validated_world_fingerprint=FINGERPRINT,
        ),
    )


@pytest.mark.parametrize("mode", [Mode.ROAD, Mode.RAIL])
def test_valid_modes_round_trip(mode: Mode) -> None:
    scenario, plan = tiny_scenario(), tiny_plan(mode)
    validate_execution_plan(plan, scenario)
    artifact = plan_artifact_bytes(plan)
    loaded = load_plan_artifact(artifact, scenario)
    assert loaded == plan
    assert plan_artifact_bytes(loaded) == artifact
    assert canonical_bytes(plan) == canonical_bytes(loaded)


def test_hash_is_canonical_and_excludes_estimates() -> None:
    plan = tiny_plan()
    same = ExecutionPlan.model_validate_json(plan.model_dump_json())
    assert canonical_bytes(plan) == canonical_bytes(same)
    assert plan_hash(plan) == plan_hash(same)
    assert canonical_bytes(plan) == canonical_bytes(plan)
    changed = plan.model_copy(update={"scenario_id": "different"})
    assert plan_hash(changed) != plan_hash(plan)
    changed = plan.model_copy(
        update={
            "routes": (
                plan.routes[0].model_copy(update={"stops": tuple(reversed(plan.routes[0].stops))}),
            )
        }
    )
    assert plan_hash(changed) != plan_hash(plan)
    estimate = EstimatedPlanMetrics(
        schema_version=1,
        plan_hash=plan_hash(plan),
        estimator_name="fixture",
        estimator_version="1",
        assumptions_digest="c" * 64,
        horizon_days=120,
        currency="GBP",
        revenue_gbp="1.00",
    )
    assert estimate.model_copy(update={"revenue_gbp": "2.00"}) != estimate
    assert plan_hash(plan) == estimate.plan_hash  # estimate changes never rewrite the plan
    verify_plan_hash(plan, estimate.plan_hash)


def test_unordered_collections_and_decimal_spelling_normalize() -> None:
    scenario = tiny_scenario()
    reordered = scenario.model_copy(update={"locations": tuple(reversed(scenario.locations))})
    assert canonical_bytes(scenario) == canonical_bytes(reordered)
    changed = scenario.model_copy(
        update={
            "economic_assumptions": scenario.economic_assumptions.model_copy(
                update={"revenue_gbp_per_cargo_unit": Decimal("2")}
            )
        }
    )
    assert canonical_bytes(scenario) == canonical_bytes(changed)
    assert scenario_hash(scenario) == scenario_hash(changed)


@pytest.mark.parametrize(
    "mutation,code",
    [
        (
            lambda p: p.model_copy(update={"scenario_id": "other"}),
            PlanningFailureCode.SCENARIO_MISMATCH,
        ),
        (
            lambda p: p.model_copy(
                update={"routes": (p.routes[0].model_copy(update={"fleet_group_id": "unknown"}),)}
            ),
            PlanningFailureCode.INVALID_FLEET,
        ),
        (
            lambda p: p.model_copy(
                update={"routes": (p.routes[0].model_copy(update={"origin_id": "unknown"}),)}
            ),
            PlanningFailureCode.UNKNOWN_NODE,
        ),
        (
            lambda p: p.model_copy(
                update={
                    "routes": (
                        p.routes[0].model_copy(
                            update={
                                "cargo_assignments": (
                                    CargoAssignment(
                                        demand_id="missing", quantity=1, unit="cargo_units"
                                    ),
                                )
                            }
                        ),
                    )
                }
            ),
            PlanningFailureCode.INVALID_PLAN,
        ),
        (
            lambda p: p.model_copy(
                update={
                    "fleet": FleetPlan(
                        groups=(p.fleet.groups[0].model_copy(update={"option_id": "missing"}),)
                    )
                }
            ),
            PlanningFailureCode.INVALID_FLEET,
        ),
    ],
)
def test_references_fail_with_typed_codes(mutation, code: PlanningFailureCode) -> None:
    with pytest.raises(PlanningValidationError) as error:
        validate_execution_plan(mutation(tiny_plan()), tiny_scenario())
    assert error.value.code is code


def test_rail_consist_is_validated_without_optimizing() -> None:
    plan = tiny_plan(Mode.RAIL)
    group = plan.fleet.groups[0]
    bad = group.model_copy(
        update={"composition": group.composition.model_copy(update={"total_length_tiles": 9})}
    )
    with pytest.raises(PlanningValidationError) as error:
        validate_execution_plan(
            plan.model_copy(update={"fleet": FleetPlan(groups=(bad,))}), tiny_scenario()
        )
    assert error.value.code is PlanningFailureCode.INVALID_FLEET


def test_strict_schema_and_numeric_values() -> None:
    raw = json.loads(plan_artifact_bytes(tiny_plan()))
    raw["plan"]["unexpected"] = 1
    with pytest.raises(PlanningValidationError):
        load_plan_artifact(json.dumps(raw).encode(), tiny_scenario())
    raw["plan"].pop("unexpected")
    raw["plan"]["schema_version"] = 2
    with pytest.raises(PlanningValidationError) as error:
        load_plan_artifact(json.dumps(raw).encode(), tiny_scenario())
    assert error.value.code is PlanningFailureCode.UNSUPPORTED_PLAN_VERSION
    with pytest.raises(ValidationError):
        EstimatedPlanMetrics(
            schema_version=1,
            plan_hash="a" * 64,
            estimator_name="e",
            estimator_version="1",
            assumptions_digest="b" * 64,
            horizon_days=1,
            currency="GBP",
            revenue_gbp="NaN",
        )
    with pytest.raises(ValidationError):
        WagonComposition(wagon_type="wagon", count=0)


def test_bad_json_and_hash_mismatch_are_rejected() -> None:
    scenario = tiny_scenario()
    with pytest.raises(PlanningValidationError):
        load_plan_artifact(b"{broken", scenario)
    raw = json.loads(plan_artifact_bytes(tiny_plan()))
    raw["plan"]["fleet"]["groups"][0]["count"] = 2
    with pytest.raises(PlanningValidationError) as error:
        load_plan_artifact(json.dumps(raw).encode(), scenario)
    assert error.value.code is PlanningFailureCode.INVALID_PLAN


def test_multimodal_plan_and_split_demand() -> None:
    road, rail = tiny_plan(Mode.ROAD), tiny_plan(Mode.RAIL)
    road_route = road.routes[0].model_copy(
        update={
            "cargo_assignments": (
                CargoAssignment(demand_id="coal-flow", quantity=50, unit="cargo_units"),
            )
        }
    )
    rail_route = rail.routes[0].model_copy(
        update={
            "cargo_assignments": (
                CargoAssignment(demand_id="coal-flow", quantity=50, unit="cargo_units"),
            )
        }
    )
    combined = road.model_copy(
        update={
            "plan_id": "mixed-plan",
            "routes": (road_route, rail_route),
            "fleet": FleetPlan(groups=road.fleet.groups + rail.fleet.groups),
            "infrastructure": InfrastructurePlan(
                actions=road.infrastructure.actions + rail.infrastructure.actions
            ),
        }
    )
    validate_execution_plan(combined, tiny_scenario())
    loaded = load_plan_artifact(plan_artifact_bytes(combined), tiny_scenario())
    assert canonical_bytes(loaded) == canonical_bytes(combined)
    overassigned = combined.model_copy(update={"routes": road.routes + rail.routes})
    with pytest.raises(PlanningValidationError) as error:
        validate_execution_plan(overassigned, tiny_scenario())
    assert error.value.code is PlanningFailureCode.INVALID_PLAN


def test_duplicate_ids_and_unknown_construction_reference() -> None:
    plan = tiny_plan()
    duplicate_route = plan.model_copy(update={"routes": plan.routes + plan.routes})
    duplicate_group = plan.model_copy(
        update={"fleet": FleetPlan(groups=plan.fleet.groups + plan.fleet.groups)}
    )
    unknown_candidate = plan.model_copy(
        update={
            "infrastructure": InfrastructurePlan(
                actions=(
                    plan.infrastructure.actions[0].model_copy(update={"candidate_id": "missing"}),
                )
                + plan.infrastructure.actions[1:]
            )
        }
    )
    for broken in (duplicate_route, duplicate_group, unknown_candidate):
        with pytest.raises(PlanningValidationError):
            validate_execution_plan(broken, tiny_scenario())


def test_invalid_mode_unit_and_rail_wagon_are_rejected() -> None:
    raw = json.loads(plan_artifact_bytes(tiny_plan()))
    raw["plan"]["routes"][0]["mode"] = "air"
    with pytest.raises(PlanningValidationError) as error:
        load_plan_artifact(json.dumps(raw).encode(), tiny_scenario())
    assert error.value.code is PlanningFailureCode.UNSUPPORTED_MODE
    with pytest.raises(ValidationError):
        CargoAssignment(demand_id="coal-flow", quantity=1, unit="kg")
    rail = tiny_plan(Mode.RAIL)
    group = rail.fleet.groups[0]
    bad_consist = group.composition.model_copy(
        update={
            "wagons": (WagonComposition(wagon_type="unknown", count=1),),
        }
    )
    bad_group = group.model_copy(update={"composition": bad_consist})
    with pytest.raises(PlanningValidationError) as error:
        validate_execution_plan(
            rail.model_copy(update={"fleet": FleetPlan(groups=(bad_group,))}), tiny_scenario()
        )
    assert error.value.code is PlanningFailureCode.INVALID_FLEET


def test_construction_cost_and_order_change_plan_hash() -> None:
    plan = tiny_plan()
    first = plan.infrastructure.actions[0]
    changed_cost = plan.model_copy(
        update={
            "infrastructure": InfrastructurePlan(
                actions=(
                    first.model_copy(
                        update={"estimated_build_cost_gbp": first.estimated_build_cost_gbp + 1}
                    ),
                )
                + plan.infrastructure.actions[1:]
            )
        }
    )
    reordered = plan.model_copy(
        update={
            "infrastructure": InfrastructurePlan(
                actions=tuple(reversed(plan.infrastructure.actions))
            )
        }
    )
    assert plan_hash(changed_cost) != plan_hash(plan)
    assert plan_hash(reordered) != plan_hash(plan)
    with pytest.raises(PlanningValidationError) as error:
        validate_execution_plan(changed_cost, tiny_scenario())
    assert error.value.code is PlanningFailureCode.UNSUPPORTED_CONSTRUCTION


def test_cargo_fleet_and_consist_changes_alter_hash() -> None:
    road = tiny_plan()
    route = road.routes[0]
    changed_assignment = route.model_copy(
        update={
            "cargo_assignments": (
                CargoAssignment(demand_id="coal-flow", quantity=40, unit="cargo_units"),
            )
        }
    )
    assert plan_hash(road.model_copy(update={"routes": (changed_assignment,)})) != plan_hash(road)
    group = road.fleet.groups[0]
    changed_count = road.model_copy(
        update={"fleet": FleetPlan(groups=(group.model_copy(update={"count": 2}),))}
    )
    assert plan_hash(changed_count) != plan_hash(road)

    rail = tiny_plan(Mode.RAIL)
    rail_group = rail.fleet.groups[0]
    changed_consist = rail_group.composition.model_copy(
        update={
            "wagons": (WagonComposition(wagon_type="wagon", count=1),),
            "total_capacity_cargo_units": 30,
            "total_length_tiles": 3,
        }
    )
    changed_rail = rail.model_copy(
        update={
            "fleet": FleetPlan(
                groups=(rail_group.model_copy(update={"composition": changed_consist}),)
            )
        }
    )
    assert plan_hash(changed_rail) != plan_hash(rail)


def test_budget_is_a_hard_constraint_but_profit_is_not() -> None:
    scenario = tiny_scenario()
    constrained = scenario.model_copy(
        update={
            "constraints": PlanningConstraints(
                permitted_modes=(Mode.ROAD, Mode.RAIL), budget_gbp="10"
            )
        }
    )
    with pytest.raises(PlanningValidationError) as error:
        validate_execution_plan(tiny_plan(), constrained)
    assert error.value.code is PlanningFailureCode.INVALID_PLAN
    estimate = EstimatedPlanMetrics(
        schema_version=1,
        plan_hash=plan_hash(tiny_plan()),
        estimator_name="fixture",
        estimator_version="1",
        assumptions_digest="c" * 64,
        horizon_days=120,
        currency="GBP",
        estimated_net_profit_gbp="-99999.00",
    )
    assert estimate.estimated_net_profit_gbp < 0
    validate_execution_plan(tiny_plan(), scenario)


def test_path_like_identifiers_and_duplicate_json_keys_rejected() -> None:
    with pytest.raises(ValidationError):
        WagonComposition(wagon_type="../escape", count=1)
    with pytest.raises(PlanningValidationError) as error:
        load_plan_artifact(b'{"plan":{},"plan":{},"plan_hash":"x"}', tiny_scenario())
    assert error.value.code is PlanningFailureCode.INVALID_PLAN


def test_world_manifest_integrity_and_catalog_resolution() -> None:
    scenario, plan = tiny_scenario(), tiny_plan()
    broken = scenario.model_copy(
        update={"world_manifest": _manifest().model_copy(update={"source_digest": "e" * 64})}
    )
    with pytest.raises(PlanningValidationError) as error:
        validate_execution_plan(plan, broken)
    assert error.value.code is PlanningFailureCode.SCENARIO_MISMATCH

    manifest = _manifest().model_copy(update={"cargo_types": ("MAIL",)})
    fingerprint = world_manifest_hash(manifest)
    scenario = scenario.model_copy(
        update={"world_manifest": manifest, "world_fingerprint": fingerprint}
    )
    plan = plan.model_copy(
        update={
            "world_fingerprint": fingerprint,
            "validation": plan.validation.model_copy(
                update={"validated_world_fingerprint": fingerprint}
            ),
        }
    )
    with pytest.raises(PlanningValidationError) as error:
        validate_execution_plan(plan, scenario)
    assert error.value.code is PlanningFailureCode.INVALID_PLAN


def test_explicit_service_orders_and_capacity() -> None:
    scenario, plan = tiny_scenario(), tiny_plan()
    group = plan.fleet.groups[0]
    too_few_trips = group.model_copy(update={"planned_trips_per_vehicle": 2})
    with pytest.raises(PlanningValidationError) as error:
        validate_execution_plan(
            plan.model_copy(update={"fleet": FleetPlan(groups=(too_few_trips,))}), scenario
        )
    assert error.value.code is PlanningFailureCode.INVALID_FLEET

    route = plan.routes[0]
    bad_order = route.model_copy(
        update={
            "stops": (
                route.stops[0],
                RouteStop(location_id="road-depot", role=StopRole.PICKUP),
                route.stops[1],
                route.stops[2],
            )
        }
    )
    with pytest.raises(PlanningValidationError) as error:
        validate_execution_plan(plan.model_copy(update={"routes": (bad_order,)}), scenario)
    assert error.value.code is PlanningFailureCode.INVALID_PLAN


def test_unbuildable_manifest_tile_is_rejected() -> None:
    scenario, plan = tiny_scenario(), tiny_plan()
    manifest = _manifest().model_copy(
        update={
            "buildable_tiles": tuple(
                tile for tile in _manifest().buildable_tiles if tile != Tile(x=10, y=4)
            )
        }
    )
    fingerprint = world_manifest_hash(manifest)
    scenario = scenario.model_copy(
        update={"world_manifest": manifest, "world_fingerprint": fingerprint}
    )
    plan = plan.model_copy(
        update={
            "world_fingerprint": fingerprint,
            "validation": plan.validation.model_copy(
                update={"validated_world_fingerprint": fingerprint}
            ),
        }
    )
    with pytest.raises(PlanningValidationError) as error:
        validate_execution_plan(plan, scenario)
    assert error.value.code is PlanningFailureCode.UNSUPPORTED_CONSTRUCTION


def test_prepared_site_and_runtime_pins_cannot_drift() -> None:
    scenario, plan = tiny_scenario(), tiny_plan()
    moved = scenario.model_copy(
        update={
            "locations": tuple(
                location.model_copy(update={"tile": Tile(x=6, y=4)})
                if location.location_id == "road-station-a"
                else location
                for location in scenario.locations
            )
        }
    )
    with pytest.raises(PlanningValidationError) as error:
        validate_execution_plan(plan, moved)
    assert error.value.code is PlanningFailureCode.SCENARIO_MISMATCH
    wrong_pin = scenario.model_copy(update={"openttd_version": "14.0"})
    with pytest.raises(PlanningValidationError) as error:
        validate_execution_plan(plan, wrong_pin)
    assert error.value.code is PlanningFailureCode.SCENARIO_MISMATCH


def test_rail_capacity_is_checked_for_each_cargo_type() -> None:
    scenario, plan = tiny_scenario(), tiny_plan(Mode.RAIL)
    manifest = _manifest().model_copy(
        update={
            "cargo_types": ("COAL", "MAIL"),
            "vehicle_types": ("lorry", "engine", "wagon", "mail-wagon"),
        }
    )
    fingerprint = world_manifest_hash(manifest)
    rail_option = scenario.fleet_options[1]
    assert isinstance(rail_option, RailFleetOption)
    mail_wagon = _vehicle("mail-wagon", 30, 1).model_copy(
        update={"compatible_cargo_types": ("MAIL",)}
    )
    rail_option = rail_option.model_copy(
        update={"wagon_options": rail_option.wagon_options + (mail_wagon,)}
    )
    mail_demand = CargoDemand(
        demand_id="mail-flow",
        cargo_type="MAIL",
        origin_id="origin",
        destination_id="destination",
        quantity=100,
        unit="cargo_units",
        earliest_day=0,
        latest_delivery_day=119,
        source=SOURCE,
    )
    scenario = scenario.model_copy(
        update={
            "world_manifest": manifest,
            "world_fingerprint": fingerprint,
            "cargo_demands": scenario.cargo_demands + (mail_demand,),
            "fleet_options": (scenario.fleet_options[0], rail_option),
        }
    )
    route = plan.routes[0].model_copy(
        update={
            "cargo_assignments": (
                CargoAssignment(demand_id="coal-flow", quantity=40, unit="cargo_units"),
                CargoAssignment(demand_id="mail-flow", quantity=20, unit="cargo_units"),
            )
        }
    )
    group = plan.fleet.groups[0]
    composition = RailComposition(
        mode=Mode.RAIL,
        locomotive_type="engine",
        wagons=(
            WagonComposition(wagon_type="wagon", count=1),
            WagonComposition(wagon_type="mail-wagon", count=1),
        ),
        total_capacity_cargo_units=60,
        total_length_tiles=4,
    )
    group = group.model_copy(
        update={"demand_ids": ("coal-flow", "mail-flow"), "composition": composition}
    )
    plan = plan.model_copy(
        update={
            "world_fingerprint": fingerprint,
            "validation": plan.validation.model_copy(
                update={"validated_world_fingerprint": fingerprint}
            ),
            "routes": (route,),
            "fleet": FleetPlan(groups=(group,)),
        }
    )
    with pytest.raises(PlanningValidationError) as error:
        validate_execution_plan(plan, scenario)
    assert error.value.code is PlanningFailureCode.INVALID_FLEET
