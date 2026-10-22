"""Explicit additional vehicles preserve demand and default P05 identities."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.experiments.capacity_experiment import compare_capacity_allocations
from app.planning.canonical import canonical_bytes, scenario_hash
from app.planning.domain import PlanningScenario
from app.planning.optimizer import optimize_candidate_network
from app.planning.validation import PlanningValidationError, validate_execution_plan


@pytest.fixture
def scenario():
    value = json.loads(
        (Path(__file__).parent / "fixtures/multi_service/scenario.json").read_bytes()
    )
    for demand in value["cargo_demands"]:
        demand["quantity"] = 20
    value["fleet_options"][0]["vehicle"]["capacity_cargo_units"] = 20
    value["constraints"]["budget_gbp"] = "500000"
    return PlanningScenario.model_validate_json(json.dumps(value))


def test_explicit_extra_vehicle_changes_allocation_not_demand(scenario):
    mapping = {f"S{i + 1}": d.demand_id for i, d in enumerate(scenario.cargo_demands)}
    before = scenario_hash(scenario)
    rows = compare_capacity_allocations(scenario, mapping)
    assert scenario_hash(scenario) == before
    assert [r["allocation"] for r in rows] == [
        dict(S1=1, S2=1, S3=1),
        dict(S1=1, S2=2, S3=1),
        dict(S1=1, S2=1, S3=2),
    ]
    for row in rows:
        assert row["scenario"]["cargo_demands"] == scenario.model_dump(mode="json")["cargo_demands"]
        assert row["independently_validated"]
    baseline = scenario.model_dump(mode="json")
    assert "minimum_vehicles_by_demand" not in baseline["constraints"]["network_selection"]
    assert b'"minimum_vehicles_by_demand"' not in canonical_bytes(scenario)


def test_validator_rejects_missing_explicit_extra_vehicle(scenario):
    original = optimize_candidate_network(scenario).plan
    value = scenario.model_dump(mode="json")
    value["constraints"]["network_selection"]["minimum_vehicles_by_demand"] = {
        scenario.cargo_demands[0].demand_id: 2
    }
    variant = PlanningScenario.model_validate_json(json.dumps(value))
    plan = original.model_copy(update={"planner_inputs_digest": scenario_hash(variant)})
    with pytest.raises(PlanningValidationError, match="explicit minimum vehicle allocation"):
        validate_execution_plan(plan, variant)


@pytest.mark.parametrize(
    "allocation", [{"unknown": 1}, {"unknown": True}, {"unknown": 0}, {"unknown": -1}]
)
def test_invalid_allocation_rejected(scenario, allocation):
    value = scenario.model_dump(mode="json")
    value["constraints"]["network_selection"]["minimum_vehicles_by_demand"] = allocation
    with pytest.raises(ValidationError):
        PlanningScenario.model_validate_json(json.dumps(value))


@pytest.mark.parametrize("count", [True, 0, -1, 4])
def test_minimum_count_is_strict_positive_and_bounded(scenario, count):
    value = scenario.model_dump(mode="json")
    value["constraints"]["network_selection"]["max_vehicles"] = 3
    value["constraints"]["network_selection"]["minimum_vehicles_by_demand"] = {
        scenario.cargo_demands[0].demand_id: count
    }
    with pytest.raises(ValidationError):
        PlanningScenario.model_validate_json(json.dumps(value))


def test_original_services_cannot_be_sacrificed_for_extra_vehicle(scenario):
    value = scenario.model_dump(mode="json")
    value["constraints"]["budget_gbp"] = "0"
    constrained = PlanningScenario.model_validate_json(json.dumps(value))
    mapping = {f"S{i + 1}": d.demand_id for i, d in enumerate(scenario.cargo_demands)}
    rows = compare_capacity_allocations(constrained, mapping)
    assert all(not row["feasible"] for row in rows)


def test_allocation_hash_is_independent_of_mapping_order(scenario):
    value = scenario.model_dump(mode="json")
    mapping = {d.demand_id: 1 for d in scenario.cargo_demands}
    value["constraints"]["network_selection"]["minimum_vehicles_by_demand"] = mapping
    first = PlanningScenario.model_validate_json(json.dumps(value))
    value["constraints"]["network_selection"]["minimum_vehicles_by_demand"] = dict(
        reversed(list(mapping.items()))
    )
    second = PlanningScenario.model_validate_json(json.dumps(value))
    assert scenario_hash(first) == scenario_hash(second)


def test_baseline_numbers_are_observed_inputs_not_attempt19_constants():
    from app.experiments.capacity_experiment import observed_capacity_baseline

    report = {
        "totals": [{"scope": "network", "delivered_cargo": 12, "revenue": 34}],
        "lifecycle": {"elapsed_economy_days": 56},
        "finance": {"capex": 78},
    }
    assert observed_capacity_baseline(report) == {
        "cargo": 12,
        "network_revenue_gbp": 34,
        "economy_days": 56,
        "observed_capex_gbp": 78,
    }
