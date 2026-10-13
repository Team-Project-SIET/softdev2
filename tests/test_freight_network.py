"""Qualified fake-peer P08 -> shared CP-SAT -> multi-route ExecutionPlan; no launches."""

import asyncio
import json
import socket
import subprocess
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from test_qualification_coordinator import QualificationWire, collect
from test_supplemental_planning_contracts import correspondence, fact_dict, facts

from app.planning.canonical import canonical_bytes, plan_hash
from app.planning.domain import ResourceLimit
from app.planning.optimizer import OptimizerFailure, optimize_candidate_network
from app.planning.p08_adapter import MonthlyBatchPolicy, adapt_planning_facts
from app.planning.p08_network import generate_freight_network
from app.planning.validation import PlanningValidationError, validate_execution_plan
from app.simulation.openttd.cargo_page import CargoCatalogRecord
from app.simulation.openttd.planning_fact_input import ValidatedPlanningFactInput
from app.simulation.openttd.supplemental_planning_facts import PlanningFactError
from app.simulation.openttd.world_planning_observation import WorldPlanningObservation


@pytest.fixture(autouse=True)
def no_native(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("controlled network attempted native process or connection")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.fixture(scope="module")
def packages():
    async def qualified():
        wire = QualificationWire(industries=(2, 17, 30, 40), produces=(1,))
        wire.accepts = (1,)
        wire.metrics = (80, 0, 0)
        result = await collect(wire, await wire.owner())
        return WorldPlanningObservation(result.verification.stability.final, result)

    def record(i, label, freight, effect, classes):
        return CargoCatalogRecord(i, f"{i:08X}", freight, effect, classes)

    with patch("test_structural_world.CargoCatalogRecord", side_effect=record):
        world = asyncio.run(qualified())
    policy = MonthlyBatchPolicy(
        start_date=date(2001, 1, 1), delivery_batch_limit=40, budget_gbp=Decimal(4000)
    )
    inputs = []
    for producer, acceptor, row, width in ((2, 17, 1, 6), (2, 30, 4, 6), (40, 30, 7, 9)):
        d = fact_dict(world)
        d["engines"][0]["purchase_cost_gbp"] = 500
        start_y = 1 if row == 1 else row - 1
        d["region"] = dict(x=0, y=start_y, width=width, height=2)
        prototype = d["tiles"][0]
        map_width = world.context.world.map_width
        # Separate road rows; the third corridor costs more.
        eligible = {(x, y) for y in (1, 4, 7) for x in range(9 if y == 7 else 6)}
        eligible |= {(1, 2), (1, 3), (1, 6)}
        d["tiles"] = [
            dict(prototype, tile_id=y * map_width + x, x=x, y=y, buildable=(x, y) in eligible)
            for y in range(start_y, start_y + 2)
            for x in range(width)
        ]
        d["coverage_scopes"] = [
            dict(industry_id=producer, cargo_id=1, role="pickup"),
            dict(industry_id=acceptor, cargo_id=1, role="delivery"),
        ]
        d["coverage"] = [
            dict(
                tile_id=t["tile_id"],
                **scope,
                producer_count=1,
                acceptance_eighths=8,
                industry_covered=t["y"] == row
                and t["x"] == (0 if scope["role"] == "pickup" else width - 1),
            )
            for t in d["tiles"]
            for scope in d["coverage_scopes"]
        ]
        inputs.append(
            adapt_planning_facts(
                ValidatedPlanningFactInput(world, facts(world, d), correspondence(world)), policy
            )
        )
    return tuple(inputs)


@pytest.fixture
def network(packages):
    return generate_freight_network(packages, max_vehicles=4)


def test_qualified_network_selects_two_cheapest_services(network):
    assert len(network.services) == len(network.scenario.cargo_demands) == 3
    assert network.classification == "CONTROLLED_MULTI_SERVICE_SCENARIO"
    assert not network.native_execution_ready
    result = optimize_candidate_network(network.scenario)
    validate_execution_plan(result.plan, network.scenario)
    assert len(result.plan.routes) == 2
    selected = {r.cargo_assignments[0].demand_id for r in result.plan.routes}
    assert selected == {"benchmark-2-1-17", "benchmark-2-1-30"}
    # 2 vehicles per 40-unit service. Supply 80, fleet 4, CAPEX 2580 fits budget 4000.
    assert sum(g.count for g in result.plan.fleet.groups) == 4
    assert result.metrics.predicted_delivered_cargo_units == 80
    assert result.metrics.infrastructure_spend_gbp == 580
    assert result.metrics.vehicle_purchase_cost_gbp == 2000
    depots = [a for a in result.plan.infrastructure.actions if a.kind == "depot"]
    assert len(depots) == 2
    assert plan_hash(result.plan) == plan_hash(optimize_candidate_network(network.scenario).plan)


def test_shared_supply_limits_selection_and_validator_catches_oversubscription(network):
    plan = optimize_candidate_network(network.scenario).plan
    selection = network.scenario.constraints.network_selection
    supplies = tuple(
        s.model_copy(update={"quantity": 40}) if s.origin_id == "industry-2" else s
        for s in selection.supplies
    )
    scenario = network.scenario.model_copy(
        update={
            "constraints": network.scenario.constraints.model_copy(
                update={"network_selection": selection.model_copy(update={"supplies": supplies})}
            )
        }
    )
    with pytest.raises(PlanningValidationError, match="shared producer supply"):
        validate_execution_plan(plan, scenario)
    selected = optimize_candidate_network(scenario).plan
    assert len(selected.routes) == 2
    assert {r.origin_id for r in selected.routes} == {"industry-2", "industry-40"}


def test_capacity_and_budget_tradeoffs(network):
    scenario = network.scenario
    selection = scenario.constraints.network_selection
    for update, expected in (
        ({"max_vehicles": 2}, 1),
        (
            {
                "resource_limits": (
                    ResourceLimit(
                        candidate_id=network.services[0]
                        .scenario.infrastructure_candidates[2]
                        .candidate_id,
                        max_vehicles=1,
                    ),
                )
            },
            2,
        ),
    ):
        changed = scenario.model_copy(
            update={
                "constraints": scenario.constraints.model_copy(
                    update={"network_selection": selection.model_copy(update=update)}
                )
            }
        )
        plan = optimize_candidate_network(changed).plan
        assert len(plan.routes) == expected
        validate_execution_plan(plan, changed)
    reduced = scenario.model_copy(
        update={
            "constraints": scenario.constraints.model_copy(update={"budget_gbp": Decimal(1300)})
        }
    )
    assert len(optimize_candidate_network(reduced).plan.routes) == 1
    empty = scenario.model_copy(
        update={"constraints": scenario.constraints.model_copy(update={"budget_gbp": Decimal(0)})}
    )
    with pytest.raises(OptimizerFailure, match="no positive feasible"):
        optimize_candidate_network(empty)


def test_p08_rejects_duplicate_od_and_conflicting_shared_facts(packages):
    with pytest.raises(PlanningFactError, match="duplicate OD"):
        generate_freight_network((packages[0], packages[0]), max_vehicles=4)
    from dataclasses import replace

    p = packages[1]
    changed = p.admitted.supplemental.model_copy(
        update={
            "engines": tuple(
                e.model_copy(update={"purchase_cost_gbp": e.purchase_cost_gbp + 1})
                for e in p.facts.engines
            )
        }
    )
    bad = adapt_planning_facts(replace(p.admitted, supplemental=changed), p.policy)
    with pytest.raises(PlanningFactError, match="conflicting shared facts"):
        generate_freight_network((packages[0], bad), max_vehicles=4)


def test_fixture_matches_generated_p08_scenario(network):
    path = Path(__file__).parent / "fixtures/multi_service/scenario.json"
    assert json.loads(path.read_text()) == json.loads(canonical_bytes(network.scenario))


def test_same_qualified_service_can_share_exact_assets_without_duplicate_spending(network):
    # Two explicit batch services over identical qualified infrastructure.
    # Full atomic candidate reuse is supported; partial road-bit reuse is not inferred.
    scenario = network.scenario
    selection = scenario.constraints.network_selection
    first = scenario.cargo_demands[0]
    second = first.model_copy(update={"demand_id": "second-batch"})
    resources = next(r for r in selection.service_resources if r.demand_id == first.demand_id)
    combined = scenario.model_copy(
        update={
            "cargo_demands": (first, second),
            "constraints": scenario.constraints.model_copy(
                update={
                    "network_selection": selection.model_copy(
                        update={
                            "service_resources": (
                                resources,
                                resources.model_copy(update={"demand_id": second.demand_id}),
                            )
                        }
                    )
                }
            ),
        }
    )
    result = optimize_candidate_network(combined)
    assert len(result.plan.routes) == 2
    assert len(result.plan.infrastructure.actions) == 4
    assert all(len(a.route_ids) == 2 for a in result.plan.infrastructure.actions)
    assert result.metrics.infrastructure_spend_gbp == 290
    assert result.metrics.vehicle_purchase_cost_gbp == 2000
    validate_execution_plan(result.plan, combined)


def test_network_p07_reports_service_and_aggregate_estimates_without_inventing_actuals(network):
    from app.experiments.freight_network import evaluate_freight_network

    result = optimize_candidate_network(network.scenario)
    report = evaluate_freight_network(result.plan, network.scenario)
    assert len(report.services) == 2
    assert all(s.status == "unobserved" for s in report.services)
    metrics = {m.name: m for m in report.metrics}
    assert metrics["delivered_cargo"].planned == 80
    assert metrics["total_capex"].planned == 2580
    assert metrics["infrastructure_capex"].planned == 580
    assert metrics["vehicle_purchase"].planned == 2000
    for name in (
        "delivered_cargo",
        "total_capex",
        "delivery_revenue",
        "vehicle_profit",
        "operating_costs",
        "net_return",
    ):
        assert metrics[name].actual is None
    assert not report.native_execution_ready


def test_network_cli_runs_saved_scenario_without_native_operations(tmp_path):
    from app.planning.network_cli import main

    path = Path(__file__).parent / "fixtures/multi_service/scenario.json"
    assert main([str(path), "--output", str(tmp_path)]) == 0
    plan = json.loads((tmp_path / "execution-plan.json").read_text())
    assert len(plan["routes"]) == 2
    assert json.loads((tmp_path / "evaluation.json").read_text())["native_execution_ready"] is False


def test_unavailable_optional_service_does_not_abort_feasible_network(network):
    scenario = network.scenario
    blocked = scenario.cargo_demands[0].model_copy(
        update={
            "earliest_day": 1,
            "latest_delivery_day": 1,
        }
    )
    changed = scenario.model_copy(update={"cargo_demands": (blocked, *scenario.cargo_demands[1:])})
    result = optimize_candidate_network(changed)
    assert len(result.plan.routes) == 2
    assert blocked.demand_id not in {
        a.demand_id for r in result.plan.routes for a in r.cargo_assignments
    }
    validate_execution_plan(result.plan, changed)


def test_independent_verified_native_runs_are_not_network_actuals(network):
    from app.experiments.freight_network import evaluate_freight_network

    retained = (
        Path(__file__).parents[1] / "artifacts/runtime/openttd-15.3-first-freight-delivery-attempt9"
    )
    if not (retained / "artifact-manifest.sha256").exists():
        pytest.skip("optional retained native evidence not installed")
    plan = optimize_candidate_network(network.scenario).plan
    report = evaluate_freight_network(plan, network.scenario, {plan.routes[0].route_id: retained})
    assert report.services[0].evidence.status == "verified-delivery"
    assert report.services[0].status == "unattributed"
    assert all(m.actual is None for m in report.metrics)
    assert all(m.actual is None for m in report.services[0].metrics)


def test_multi_route_plan_stays_outside_single_service_executor(network):
    from app.simulation.openttd.freight_planning import compile_freight_service

    plan = optimize_candidate_network(network.scenario).plan
    with pytest.raises(PlanningValidationError):
        compile_freight_service(network.services[0], plan)


def test_p07_verified_batch_aggregation_excludes_failures_and_preserves_unknown_opex():
    from app.experiments.freight_evaluation import FreightMetric
    from app.experiments.freight_network import ServiceEvaluation, verified_batch_subtotals

    # Pure aggregation fixtures. They are not retained/native verification evidence.
    def service(route, status, cargo, profit):
        metrics = tuple(
            FreightMetric(
                name=name,
                unit=unit,
                scope="controlled-aggregation-test",
                actual=amount,
                provenance="Controlled arithmetic fixture",
            )
            for name, amount, unit in (
                ("delivered_cargo", cargo, "cargo_units"),
                ("vehicle_profit", profit, "GBP"),
                ("vehicle_purchase", Decimal(500), "GBP"),
                ("operating_costs", None, "GBP"),
            )
        )
        return ServiceEvaluation(route_id=route, demand_id=route, status=status, metrics=metrics)

    first = service("a", "verified-delivery", Decimal(20), Decimal(100))
    second = service("b", "verified-delivery", Decimal(30), Decimal(150))
    failed = service("c", "failed", Decimal(999), Decimal(999))
    m = {m.name: m for m in verified_batch_subtotals((first, second, failed))}
    assert m["delivered_cargo"].actual == 50
    assert m["vehicle_profit"].actual == 250
    assert m["vehicle_purchase"].actual == 1000
    assert m["operating_costs"].actual is None
    assert all(m.actual is None for m in verified_batch_subtotals((failed,)))


def test_capacity_validator_rejects_tampered_shared_limits(network):
    scenario = network.scenario
    plan = optimize_candidate_network(scenario).plan
    selection = scenario.constraints.network_selection
    depot = next(a for a in plan.infrastructure.actions if a.kind == "depot")
    for change, message in (
        ({"max_vehicles": 2}, "shared vehicle limit"),
        (
            {"resource_limits": (ResourceLimit(candidate_id=depot.candidate_id, max_vehicles=1),)},
            "shared infrastructure capacity",
        ),
    ):
        changed = scenario.model_copy(
            update={
                "constraints": scenario.constraints.model_copy(
                    update={"network_selection": selection.model_copy(update=change)}
                )
            }
        )
        with pytest.raises(PlanningValidationError, match=message):
            validate_execution_plan(plan, changed)


def test_resource_limit_on_unavailable_service_does_not_block_others(network):
    scenario = network.scenario
    selection = scenario.constraints.network_selection
    blocked = scenario.cargo_demands[0].model_copy(
        update={"earliest_day": 1, "latest_delivery_day": 1}
    )
    resource = next(r for r in selection.service_resources if r.demand_id == blocked.demand_id)
    depot = next(
        c
        for c in scenario.infrastructure_candidates
        if c.candidate_id in resource.candidate_ids and c.kind == "depot"
    )
    changed = scenario.model_copy(
        update={
            "cargo_demands": (blocked, *scenario.cargo_demands[1:]),
            "constraints": scenario.constraints.model_copy(
                update={
                    "network_selection": selection.model_copy(
                        update={
                            "resource_limits": (
                                ResourceLimit(candidate_id=depot.candidate_id, max_vehicles=1),
                            )
                        }
                    )
                }
            ),
        }
    )
    plan = optimize_candidate_network(changed).plan
    assert len(plan.routes) == 2
    validate_execution_plan(plan, changed)


def test_package_order_does_not_change_scenario_or_plan(packages):
    forward = generate_freight_network(packages, max_vehicles=4)
    reverse = generate_freight_network(tuple(reversed(packages)), max_vehicles=4)
    assert canonical_bytes(forward.scenario) == canonical_bytes(reverse.scenario)
    assert plan_hash(optimize_candidate_network(forward.scenario).plan) == plan_hash(
        optimize_candidate_network(reverse.scenario).plan
    )
