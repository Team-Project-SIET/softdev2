"""Independent controlled integration and immutable historical replay checks."""

import asyncio
import socket
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest
import test_freight_network

from app.experiments.freight_network import evaluate_freight_network
from app.planning.canonical import plan_hash
from app.planning.domain import ExecutionPlan, PlanningScenario
from app.planning.optimizer import optimize_candidate_network
from app.planning.p08_adapter import adapt_planning_facts
from app.planning.p08_network import generate_freight_network
from app.planning.validation import validate_execution_plan
from app.simulation.openttd.freight_native_network import aggregate_receipt
from app.simulation.openttd.freight_planning import compile_freight_network

packages = test_freight_network.packages


@pytest.fixture(autouse=True)
def no_native(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("offline scaling test attempted native process or Admin connection")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def three_service_network(packages):
    inputs = tuple(
        adapt_planning_facts(p.admitted, p.policy.model_copy(update={"delivery_batch_limit": 30}))
        for p in packages
    )
    return generate_freight_network(inputs, max_vehicles=3)


def test_three_services_selected_compiled_and_aggregated_without_forcing(
    packages, monkeypatch, tmp_path
):
    network = three_service_network(packages)
    optimized = optimize_candidate_network(network.scenario)
    plan = optimized.plan
    validate_execution_plan(plan, network.scenario)
    services = compile_freight_network(network, plan)
    assert len(services) == len(plan.routes) == 3
    assert optimized.metrics.predicted_delivered_cargo_units == 90
    assert {r.cargo_assignments[0].demand_id for r in plan.routes} == {
        d.demand_id for d in network.scenario.cargo_demands
    }
    assert plan_hash(plan) == plan_hash(optimize_candidate_network(network.scenario).plan)
    receipts = [
        dict(
            route_id=route_id,
            vehicle=23 + n,
            delivered=20,
            payment_income=100 + n,
            vehicle_profit_delta=90 + n,
            construction_purchase_spending=560,
            mutation_costs=[10] * 6 + [500],
        )
        for n, (route_id, _) in enumerate(services)
    ]
    aggregate = aggregate_receipt(plan, services, receipts)
    assert aggregate["delivered"] == 60
    assert aggregate["payment_income"] == 303
    assert aggregate["actual_capex"] == 1680
    assert aggregate["infrastructure_capex"] == 180
    assert aggregate["vehicle_purchase"] == 1500
    assert aggregate["operating_costs"] is None
    with pytest.raises(ValueError, match="exact selected"):
        aggregate_receipt(plan, services, receipts[:-1])
    duplicate_vehicle = [dict(r) for r in receipts]
    duplicate_vehicle[2]["vehicle"] = duplicate_vehicle[0]["vehicle"]
    with pytest.raises(ValueError, match="independent network vehicles"):
        aggregate_receipt(plan, services, duplicate_vehicle)
    from app.simulation.openttd import freight_native_network

    monkeypatch.setattr(freight_native_network, "verify_network_receipt", lambda _: aggregate)
    report = evaluate_freight_network(plan, network.scenario, native_network_directory=tmp_path)
    assert len(report.services) == report.verified_service_count == 3
    metrics = {m.name: m for m in report.metrics}
    assert metrics["delivered_cargo"].planned == 90
    assert metrics["delivered_cargo"].actual == 60
    assert metrics["total_capex"].actual == 1680
    assert metrics["operating_costs"].actual is None
    assert metrics["net_return"].actual is None


def test_extra_cash_does_not_override_shared_fleet_constraint(packages):
    network = three_service_network(packages)
    scenario = network.scenario
    selection = scenario.constraints.network_selection
    constrained = scenario.model_copy(
        update={
            "constraints": scenario.constraints.model_copy(
                update={
                    "budget_gbp": Decimal(500000),
                    "network_selection": selection.model_copy(update={"max_vehicles": 2}),
                }
            )
        }
    )
    plan = optimize_candidate_network(constrained).plan
    assert len(plan.routes) == 2
    validate_execution_plan(plan, constrained)


def test_attempt14_historical_receipt_still_replays_offline():
    directory = (
        Path(__file__).parents[1]
        / "artifacts/runtime/openttd-15.3-first-freight-delivery-attempt14"
    )
    if not (directory / "artifact-manifest.sha256").exists():
        pytest.skip("optional retained native evidence not installed")
    plan = ExecutionPlan.model_validate_json((directory / "execution-plan.json").read_bytes())
    scenario = PlanningScenario.model_validate_json(
        (directory / "planning-scenario.json").read_bytes()
    )
    report = evaluate_freight_network(plan, scenario, native_network_directory=directory)
    assert report.verified_service_count == 2
    metrics = {m.name: m.actual for m in report.metrics}
    assert metrics["delivered_cargo"] == 40
    assert metrics["delivery_revenue"] == 682
    assert metrics["total_capex"] == 19101
    assert metrics["operating_costs"] is None
    assert metrics["net_return"] is None


@pytest.mark.parametrize("selected_count, service_limit", [(2, 3), (3, 3), (2, 2)])
def test_native_execution_requires_exact_three_before_selection(
    packages, monkeypatch, tmp_path, selected_count, service_limit
):
    from types import SimpleNamespace

    from app.simulation.openttd import freight_native_network as native

    inputs = tuple(
        adapt_planning_facts(p.admitted, p.policy.model_copy(update={"delivery_batch_limit": 30}))
        for p in packages
    )
    network = generate_freight_network(inputs, max_vehicles=selected_count)
    plan = optimize_candidate_network(network.scenario).plan
    services = compile_freight_network(network, plan)
    assert len(services) == selected_count

    async def planned(*args):
        native.write_json(tmp_path / "execution-plan.json", plan.model_dump(mode="json"))
        return network, plan, services, "saved-source"

    class SelectionReached(Exception):
        pass

    def selection(*args, **kwargs):
        raise SelectionReached

    monkeypatch.setattr(native, "plan_network_world", planned)
    monkeypatch.setattr(native, "validate_game_time_version", lambda _: None)
    monkeypatch.setattr(type(services[0][1]), "selection_request", selection)
    expected = ValueError if selected_count != service_limit else SelectionReached
    match = (
        "THREE_SERVICE_ADMISSION_REQUIRES_EXACTLY_3_SELECTED" if expected is ValueError else None
    )
    with pytest.raises(expected, match=match):
        asyncio.run(
            native.execute_network(
                SimpleNamespace(planning_read_count=0),
                SimpleNamespace(directory=tmp_path),
                None,
                None,
                None,
                None,
                {"network_service_limit": service_limit, "delivery_batch_limit": 30},
                {},
            )
        )
    assert (
        ExecutionPlan.model_validate_json((tmp_path / "execution-plan.json").read_bytes()) == plan
    )
