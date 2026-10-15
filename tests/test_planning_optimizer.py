"""P05 behavior at the scenario -> validated plan and estimates boundary."""

from decimal import Decimal

import pytest

from app.planning.canonical import canonical_bytes, plan_hash
from app.planning.domain import Mode, RailComposition, RailFleetOption, RoadFleetOption
from app.planning.optimizer import (
    OptimizerFailure,
    OptimizerFailureCode,
    optimize_candidate_network,
)
from app.planning.validation import validate_execution_plan
from tests.test_planning import tiny_scenario


def road_scenario():
    scenario = tiny_scenario()
    return scenario.model_copy(
        update={
            "constraints": scenario.constraints.model_copy(update={"permitted_modes": (Mode.ROAD,)})
        }
    )


def test_road_capacity_and_capex():
    scenario = road_scenario()
    result = optimize_candidate_network(scenario)
    validate_execution_plan(result.plan, scenario)
    assert result.plan.fleet.groups[0].count == 5
    assert result.plan.fleet.groups[0].planned_trips_per_vehicle == 1
    assert result.metrics.infrastructure_spend_gbp == Decimal("270")
    assert result.metrics.vehicle_purchase_cost_gbp == Decimal("500")
    assert result.metrics.predicted_delivered_cargo_units == 100


def test_rail_minimum_purchase_cost_consist():
    scenario = tiny_scenario()
    scenario = scenario.model_copy(
        update={
            "constraints": scenario.constraints.model_copy(update={"permitted_modes": (Mode.RAIL,)})
        }
    )
    result = optimize_candidate_network(scenario)
    group = result.plan.fleet.groups[0]
    assert isinstance(group.composition, RailComposition)
    assert group.count == 1
    assert group.composition.total_capacity_cargo_units == 120
    assert group.composition.total_length_tiles == 6
    assert group.composition.wagons[0].count == 4
    assert result.metrics.vehicle_purchase_cost_gbp == Decimal("500")
    validate_execution_plan(result.plan, scenario)


def priced(scenario, prices):
    return scenario.model_copy(
        update={
            "infrastructure_candidates": tuple(
                c.model_copy(update={"estimated_build_cost_gbp": Decimal(prices[c.candidate_id])})
                if c.candidate_id in prices
                else c
                for c in scenario.infrastructure_candidates
            )
        }
    )


def test_exact_subpenny_cost_and_canonical_tie_break():
    scenario = road_scenario()
    original = next(
        c for c in scenario.infrastructure_candidates if c.candidate_id == "road-station-a"
    )
    alternate = original.model_copy(
        update={"candidate_id": "a-cheaper", "estimated_build_cost_gbp": Decimal("24.999")}
    )
    scenario = scenario.model_copy(
        update={"infrastructure_candidates": scenario.infrastructure_candidates + (alternate,)}
    )
    result = optimize_candidate_network(scenario)
    assert "a-cheaper" in {a.candidate_id for a in result.plan.infrastructure.actions}
    assert result.metrics.infrastructure_spend_gbp == Decimal("269.999")
    scenario = priced(scenario, {"a-cheaper": "25"})
    for _ in range(3):
        result = optimize_candidate_network(scenario)
        assert "a-cheaper" in {a.candidate_id for a in result.plan.infrastructure.actions}


def test_budget_infeasible_is_typed():
    scenario = road_scenario()
    scenario = scenario.model_copy(
        update={
            "constraints": scenario.constraints.model_copy(
                update={"budget_gbp": Decimal("769.999")}
            )
        }
    )
    with pytest.raises(OptimizerFailure) as error:
        optimize_candidate_network(scenario)
    assert error.value.code == OptimizerFailureCode.BUDGET_INFEASIBLE


def test_global_shared_network_beats_independent_choices():
    scenario = tiny_scenario()
    road, rail = scenario.fleet_options
    assert isinstance(rail, RailFleetOption)
    rail = rail.model_copy(
        update={
            "locomotive": rail.locomotive.model_copy(update={"purchase_cost_gbp": Decimal("200")}),
            "wagon_options": (
                rail.wagon_options[0].model_copy(update={"purchase_cost_gbp": Decimal("20")}),
            ),
        }
    )
    first = scenario.cargo_demands[0].model_copy(update={"demand_id": "first", "quantity": 20})
    second = scenario.cargo_demands[0].model_copy(update={"demand_id": "second"})
    scenario = scenario.model_copy(
        update={"fleet_options": (road, rail), "cargo_demands": (first, second)}
    )
    independent = [
        optimize_candidate_network(scenario.model_copy(update={"cargo_demands": (d,)}))
        for d in (first, second)
    ]
    assert [r.plan.routes[0].mode for r in independent] == [Mode.ROAD, Mode.RAIL]
    result = optimize_candidate_network(scenario)
    assert [r.mode for r in result.plan.routes] == [Mode.RAIL, Mode.RAIL]
    assert result.metrics.infrastructure_spend_gbp == Decimal("270")
    assert result.metrics.vehicle_purchase_cost_gbp == Decimal("500")
    independent_capex = Decimal(0)
    for r in independent:
        assert r.metrics.infrastructure_spend_gbp is not None
        assert r.metrics.vehicle_purchase_cost_gbp is not None
        independent_capex += (
            r.metrics.infrastructure_spend_gbp + r.metrics.vehicle_purchase_cost_gbp
        )
    assert independent_capex == Decimal("920")
    assert len(result.plan.infrastructure.actions) == 4
    route_ids = {r.route_id for r in result.plan.routes}
    for action in result.plan.infrastructure.actions:
        assert set(action.route_ids) == route_ids
    assert sum(a.quantity for r in result.plan.routes for a in r.cargo_assignments) == 120
    validate_execution_plan(result.plan, scenario)


def test_overlapping_distinct_corridors_are_globally_infeasible():
    scenario = road_scenario()
    demand = scenario.cargo_demands[0].model_copy(
        update={"demand_id": "reverse", "origin_id": "destination", "destination_id": "origin"}
    )
    segment = next(
        c for c in scenario.infrastructure_candidates if c.candidate_id == "road-segment"
    )
    reverse = segment.model_copy(
        update={
            "candidate_id": "reverse-segment",
            "origin_id": segment.destination_id,
            "destination_id": segment.origin_id,
            "tiles": tuple(reversed(segment.tiles)),
        }
    )
    scenario = scenario.model_copy(
        update={
            "cargo_demands": scenario.cargo_demands + (demand,),
            "infrastructure_candidates": scenario.infrastructure_candidates + (reverse,),
        }
    )
    with pytest.raises(OptimizerFailure) as error:
        optimize_candidate_network(scenario)
    assert error.value.code == OptimizerFailureCode.GLOBALLY_INFEASIBLE


def test_station_and_fleet_prices_both_affect_selection():
    scenario = road_scenario()
    station = next(
        c for c in scenario.infrastructure_candidates if c.candidate_id == "road-station-a"
    )
    alternate = station.model_copy(
        update={"candidate_id": "expensive-station", "estimated_build_cost_gbp": Decimal("500")}
    )
    option = scenario.fleet_options[0]
    assert isinstance(option, RoadFleetOption)
    cheap = option.model_copy(
        update={
            "option_id": "cheap-small",
            "vehicle": option.vehicle.model_copy(
                update={"capacity_cargo_units": 10, "purchase_cost_gbp": Decimal("60")}
            ),
        }
    )
    scenario = scenario.model_copy(
        update={
            "infrastructure_candidates": scenario.infrastructure_candidates + (alternate,),
            "fleet_options": scenario.fleet_options + (cheap,),
        }
    )
    result = optimize_candidate_network(scenario)
    assert result.plan.fleet.groups[0].option_id == "road-option"  # £500 < ten * £60
    assert "expensive-station" not in {a.candidate_id for a in result.plan.infrastructure.actions}
    cheap = cheap.model_copy(
        update={"vehicle": cheap.vehicle.model_copy(update={"purchase_cost_gbp": Decimal("40")})}
    )
    scenario = scenario.model_copy(update={"fleet_options": scenario.fleet_options[:-1] + (cheap,)})
    result = optimize_candidate_network(scenario)
    assert result.plan.fleet.groups[0].option_id == "cheap-small"
    assert result.plan.fleet.groups[0].count == 10
    assert result.metrics.vehicle_purchase_cost_gbp == Decimal("400")


@pytest.mark.parametrize("quantity,count", [(1, 1), (20, 1), (21, 2), (101, 6)])
def test_road_vehicle_count_rounds_up(quantity, count):
    scenario = road_scenario()
    scenario = scenario.model_copy(
        update={
            "cargo_demands": (scenario.cargo_demands[0].model_copy(update={"quantity": quantity}),)
        }
    )
    result = optimize_candidate_network(scenario)
    assert result.plan.fleet.groups[0].count == count
    assert result.plan.routes[0].cargo_assignments[0].quantity == quantity


@pytest.mark.parametrize("budget", ["770", "10000", None])
def test_budget_preserves_min_capex_solution_when_feasible(budget):
    scenario = road_scenario()
    scenario = scenario.model_copy(
        update={
            "constraints": scenario.constraints.model_copy(
                update={"budget_gbp": None if budget is None else Decimal(budget)}
            )
        }
    )
    result = optimize_candidate_network(scenario)
    assert result.metrics.infrastructure_spend_gbp is not None
    assert result.metrics.vehicle_purchase_cost_gbp is not None
    assert (
        result.metrics.infrastructure_spend_gbp + result.metrics.vehicle_purchase_cost_gbp
        == Decimal("770")
    )


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("stations", OptimizerFailureCode.NO_FEASIBLE_STATION_PAIR),
        ("segments", OptimizerFailureCode.NO_CONNECTING_SEGMENT),
        ("cargo", OptimizerFailureCode.NO_COMPATIBLE_FLEET),
        ("capacity", OptimizerFailureCode.NO_COMPATIBLE_FLEET),
        ("depot", OptimizerFailureCode.NO_COMPATIBLE_FLEET),
        ("availability", OptimizerFailureCode.NO_COMPATIBLE_FLEET),
    ],
)
def test_no_alternative_has_typed_demand_failure(mutation, code):
    scenario = road_scenario()
    if mutation in ("stations", "segments", "depot"):
        from app.planning.domain import ConstructionKind

        kind = {
            "stations": ConstructionKind.STATION,
            "segments": ConstructionKind.SEGMENT,
            "depot": ConstructionKind.DEPOT,
        }[mutation]
        scenario = scenario.model_copy(
            update={
                "infrastructure_candidates": tuple(
                    c
                    for c in scenario.infrastructure_candidates
                    if not (c.mode == Mode.ROAD and c.kind == kind)
                )
            }
        )
    else:
        road = scenario.fleet_options[0]
        if mutation == "availability":
            road = road.model_copy(update={"available_from_day": 120, "available_through_day": 130})
        else:
            updates = (
                {"compatible_cargo_types": ("MAIL",)}
                if mutation == "cargo"
                else {"capacity_cargo_units": 0}
            )
            road = road.model_copy(update={"vehicle": road.vehicle.model_copy(update=updates)})
        scenario = scenario.model_copy(update={"fleet_options": (road, scenario.fleet_options[1])})
    with pytest.raises(OptimizerFailure) as error:
        optimize_candidate_network(scenario)
    assert error.value.code == code
    assert "coal-flow" in str(error.value)


def test_wrong_depot_class_rejected():
    scenario = road_scenario()
    road = scenario.fleet_options[0].model_copy(update={"depot_class": "bus"})
    scenario = scenario.model_copy(update={"fleet_options": (road, scenario.fleet_options[1])})
    with pytest.raises(OptimizerFailure) as error:
        optimize_candidate_network(scenario)
    assert error.value.code == OptimizerFailureCode.NO_COMPATIBLE_FLEET


def rail_scenario():
    scenario = tiny_scenario()
    return scenario.model_copy(
        update={
            "constraints": scenario.constraints.model_copy(update={"permitted_modes": (Mode.RAIL,)})
        }
    )


@pytest.mark.parametrize(
    "limit,count,wagons,capacity,length", [(3, 4, 1, 30, 3), (4, 2, 2, 60, 4), (6, 1, 4, 120, 6)]
)
def test_rail_length_limit_sizes_groups(limit, count, wagons, capacity, length):
    scenario = rail_scenario()
    scenario = scenario.model_copy(
        update={
            "constraints": scenario.constraints.model_copy(update={"max_train_length_tiles": limit})
        }
    )
    result = optimize_candidate_network(scenario)
    group = result.plan.fleet.groups[0]
    assert isinstance(group.composition, RailComposition)
    assert (group.count, group.composition.wagons[0].count) == (count, wagons)
    assert (group.composition.total_capacity_cargo_units, group.composition.total_length_tiles) == (
        capacity,
        length,
    )
    validate_execution_plan(result.plan, scenario)


def test_no_wagon_fits_raises_rail_failure():
    scenario = rail_scenario()
    scenario = scenario.model_copy(
        update={
            "constraints": scenario.constraints.model_copy(update={"max_train_length_tiles": 2})
        }
    )
    with pytest.raises(OptimizerFailure) as error:
        optimize_candidate_network(scenario)
    assert error.value.code == OptimizerFailureCode.RAIL_CONSIST_INFEASIBLE


def test_modes_compared_by_total_capex():
    scenario = priced(tiny_scenario(), {"rail-segment": "0"})
    result = optimize_candidate_network(scenario)
    assert result.plan.routes[0].mode == Mode.RAIL
    assert result.metrics.infrastructure_spend_gbp == Decimal("70")
    assert result.metrics.vehicle_purchase_cost_gbp == Decimal("500")


def test_canonical_output_identity_order_dependencies_and_input_immutability():
    scenario = road_scenario()
    before = canonical_bytes(scenario)
    first = optimize_candidate_network(scenario)
    reordered = scenario.model_copy(
        update={
            "locations": tuple(reversed(scenario.locations)),
            "infrastructure_candidates": tuple(reversed(scenario.infrastructure_candidates)),
            "fleet_options": tuple(reversed(scenario.fleet_options)),
        }
    )
    for candidate in (scenario, reordered, scenario):
        result = optimize_candidate_network(candidate)
        assert canonical_bytes(result.plan) == canonical_bytes(first.plan)
        assert plan_hash(result.plan) == plan_hash(first.plan)
        assert canonical_bytes(result.metrics) == canonical_bytes(first.metrics)
    assert canonical_bytes(scenario) == before
    plan = first.plan
    assert plan.planner_name == "candidate-network-optimizer"
    assert (plan.planner_version, plan.strategy_identifier, plan.strategy_version) == (
        "1",
        "min-capex",
        "1",
    )
    assert plan.world_fingerprint == scenario.world_fingerprint
    assert [s.role.value for s in plan.routes[0].stops] == ["pickup", "delivery", "depot"]
    assert [a.kind.value for a in plan.infrastructure.actions] == [
        "station",
        "station",
        "depot",
        "segment",
    ]
    seen = set()
    for action in plan.infrastructure.actions:
        assert set(action.depends_on) <= seen
        assert set(action.route_ids) == {
            r.route_id for r in plan.routes if action.construction_id in r.infrastructure_ids
        }
        seen.add(action.construction_id)
    assert set(plan.infrastructure.actions[-1].depends_on) == {
        a.construction_id for a in plan.infrastructure.actions[:2]
    }
    assert first.metrics.revenue_gbp is None
    assert first.metrics.estimated_net_profit_gbp is None
    assert first.metrics.vehicle_running_cost_gbp is None
    assert first.metrics.plan_hash == plan_hash(plan)


@pytest.mark.parametrize("cost", ["0.0000000000000000001", "100000000000000000"])
def test_unrepresentable_cp_sat_costs_fail_typed(cost):
    scenario = priced(road_scenario(), {"road-segment": cost})
    with pytest.raises(OptimizerFailure) as error:
        optimize_candidate_network(scenario)
    assert error.value.code == OptimizerFailureCode.UNSUPPORTED_SCENARIO


def test_invalid_world_identity_rejected():
    scenario = road_scenario().model_copy(update={"world_fingerprint": "f" * 64})
    with pytest.raises(OptimizerFailure) as error:
        optimize_candidate_network(scenario)
    assert error.value.code == OptimizerFailureCode.UNSUPPORTED_SCENARIO


def test_optimizer_import_boundary_in_fresh_process():
    import subprocess
    import sys

    script = """
import sys
import app.planning.optimizer
for name in sys.modules:
    assert not name.startswith((
        "sqlalchemy", "psycopg", "openttdlab", "app.database", "app.experiments",
        "app.live", "app.telemetry", "app.planning.transport",
        "app.planning.setup_evidence", "app.planning.runtime_world",
    )), name
"""
    subprocess.run([sys.executable, "-c", script], check=True)


def test_mixed_wagon_catalog_minimum_cost_and_exact_capacity():
    from app.planning.canonical import world_manifest_hash

    scenario = rail_scenario()
    rail = scenario.fleet_options[1]
    assert isinstance(rail, RailFleetOption)
    second = rail.wagon_options[0].model_copy(
        update={
            "vehicle_type": "large-wagon",
            "capacity_cargo_units": 50,
            "length_tiles": 2,
            "purchase_cost_gbp": Decimal("140"),
        }
    )
    rail = rail.model_copy(update={"wagon_options": rail.wagon_options + (second,)})
    manifest = scenario.world_manifest.model_copy(
        update={"vehicle_types": scenario.world_manifest.vehicle_types + ("large-wagon",)}
    )
    scenario = scenario.model_copy(
        update={
            "fleet_options": (scenario.fleet_options[0], rail),
            "world_manifest": manifest,
            "world_fingerprint": world_manifest_hash(manifest),
            "cargo_demands": (scenario.cargo_demands[0].model_copy(update={"quantity": 80}),),
        }
    )
    result = optimize_candidate_network(scenario)
    composition = result.plan.fleet.groups[0].composition
    assert isinstance(composition, RailComposition)
    assert {w.wagon_type: w.count for w in composition.wagons} == {"wagon": 1, "large-wagon": 1}
    assert composition.total_capacity_cargo_units == 80
    assert composition.total_length_tiles == 5
    assert result.metrics.vehicle_purchase_cost_gbp == Decimal("340")
    validate_execution_plan(result.plan, scenario)


def test_subpenny_price_cannot_tie_with_cheaper_solution():
    scenario = road_scenario()
    station = next(
        c for c in scenario.infrastructure_candidates if c.candidate_id == "road-station-a"
    )
    # Canonical tie-break favors a-expensive; exact primary objective must defeat it.
    alternate = station.model_copy(
        update={"candidate_id": "a-expensive", "estimated_build_cost_gbp": Decimal("25.001")}
    )
    scenario = scenario.model_copy(
        update={"infrastructure_candidates": scenario.infrastructure_candidates + (alternate,)}
    )
    result = optimize_candidate_network(scenario)
    assert "a-expensive" not in {a.candidate_id for a in result.plan.infrastructure.actions}
    assert result.metrics.infrastructure_spend_gbp == Decimal("270")


def test_platform_limit_and_option_limit_both_apply():
    from app.planning.canonical import world_manifest_hash

    scenario = rail_scenario()
    rail = scenario.fleet_options[1].model_copy(update={"max_train_length_tiles": 4})
    scenario = scenario.model_copy(update={"fleet_options": (scenario.fleet_options[0], rail)})
    assert optimize_candidate_network(scenario).plan.fleet.groups[0].count == 2
    locations = tuple(
        s.model_copy(update={"platform_length_tiles": 3})
        if s.location_id.startswith("rail-station")
        else s
        for s in scenario.locations
    )
    manifest = scenario.world_manifest.model_copy(
        update={
            "resolved_sites": tuple(
                s.model_copy(update={"platform_length_tiles": 3})
                if s.location_id.startswith("rail-station")
                else s
                for s in scenario.world_manifest.resolved_sites
            )
        }
    )
    scenario = scenario.model_copy(
        update={
            "locations": locations,
            "world_manifest": manifest,
            "world_fingerprint": world_manifest_hash(manifest),
        }
    )
    group = optimize_candidate_network(scenario).plan.fleet.groups[0]
    assert isinstance(group.composition, RailComposition)
    assert group.count == 4
    assert group.composition.total_length_tiles == 3


def test_rail_cargo_and_rail_type_compatibility():
    scenario = rail_scenario()
    rail = scenario.fleet_options[1]
    assert isinstance(rail, RailFleetOption)
    for option in (
        rail.model_copy(update={"rail_type": "electric"}),
        rail.model_copy(
            update={
                "wagon_options": (
                    rail.wagon_options[0].model_copy(update={"compatible_cargo_types": ("MAIL",)}),
                )
            }
        ),
    ):
        candidate = scenario.model_copy(
            update={"fleet_options": (scenario.fleet_options[0], option)}
        )
        with pytest.raises(OptimizerFailure) as error:
            optimize_candidate_network(candidate)
        assert error.value.code == OptimizerFailureCode.NO_COMPATIBLE_FLEET


def test_large_rail_catalog_has_typed_search_limit():
    from app.planning.canonical import world_manifest_hash

    scenario = rail_scenario()
    rail = scenario.fleet_options[1]
    assert isinstance(rail, RailFleetOption)
    wagons = tuple(
        rail.wagon_options[0].model_copy(update={"vehicle_type": f"wagon-{i:04}"})
        for i in range(1100)
    )
    rail = rail.model_copy(update={"wagon_options": wagons})
    manifest = scenario.world_manifest.model_copy(
        update={
            "vehicle_types": scenario.world_manifest.vehicle_types
            + tuple(w.vehicle_type for w in wagons)
        }
    )
    scenario = scenario.model_copy(
        update={
            "fleet_options": (scenario.fleet_options[0], rail),
            "world_manifest": manifest,
            "world_fingerprint": world_manifest_hash(manifest),
        }
    )
    with pytest.raises(OptimizerFailure) as error:
        optimize_candidate_network(scenario)
    assert error.value.code == OptimizerFailureCode.UNSUPPORTED_SCENARIO


def test_raw_purchase_precision_is_not_rounded_during_fleet_sizing():
    scenario = road_scenario()
    road = scenario.fleet_options[0]
    assert isinstance(road, RoadFleetOption)
    road = road.model_copy(
        update={
            "vehicle": road.vehicle.model_copy(
                update={"purchase_cost_gbp": Decimal("1." + "0" * 110 + "1")}
            )
        }
    )
    scenario = scenario.model_copy(update={"fleet_options": (road, scenario.fleet_options[1])})
    with pytest.raises(OptimizerFailure) as error:
        optimize_candidate_network(scenario)
    assert error.value.code == OptimizerFailureCode.UNSUPPORTED_SCENARIO
