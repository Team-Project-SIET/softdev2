"""Controlled alternatives do not mutate inputs or contact native OpenTTD."""

import json
import socket
import subprocess
from pathlib import Path

import pytest

from app.experiments.freight_alternatives import compare_freight_alternatives
from app.planning.domain import PlanningScenario


@pytest.fixture
def scenario():
    value = json.loads(
        (Path(__file__).parent / "fixtures/multi_service/scenario.json").read_bytes()
    )
    for demand in value["cargo_demands"]:
        demand["quantity"] = 20
    value["fleet_options"][0]["vehicle"]["capacity_cargo_units"] = 20
    value["constraints"]["budget_gbp"] = "500000"
    value["constraints"]["network_selection"]["max_vehicles"] = 3
    return PlanningScenario.model_validate_json(json.dumps(value))


def test_alternatives_are_controlled_and_keep_optimizer_objective(monkeypatch, scenario):
    def forbidden(*args, **kwargs):
        raise AssertionError("native launch/connection forbidden")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    before = scenario.model_dump_json()
    report = compare_freight_alternatives(scenario)
    rows = {row["name"]: row for row in report["rows"]}
    assert scenario.model_dump_json() == before
    assert report["native_launches"] == report["admin_connections"] == 0
    assert all(row["independently_validated"] for row in rows.values())
    assert (rows["baseline"]["served_planning_units"], rows["baseline"]["vehicles"]) == (60, 3)
    assert rows["fleet_limit_6"]["allocation"] == rows["baseline"]["allocation"]
    assert rows["capacity_10"]["vehicles"] == 6
    assert rows["capacity_40"]["vehicles"] == 3
    assert rows["demand_40_limit_3"]["served_planning_units"] == 40
    assert rows["demand_40_limit_6"]["served_planning_units"] == 120
    assert rows["demand_40_limit_6"]["vehicles"] == 6
    for index in range(3):
        row = rows[f"extra_vehicle_service_{index}"]
        assert row["served_planning_units"] == 80
        assert sorted(row["allocation"].values()) == [1, 1, 2]
    assert all(row["planned_trips_per_vehicle"] == [1] for row in rows.values())
    assert float(rows["infrastructure_double_cost"]["estimated_infrastructure_gbp"]) == (
        2 * float(rows["baseline"]["estimated_infrastructure_gbp"])
    )


def test_infeasible_budget_is_reported(scenario):
    value = scenario.model_dump(mode="json")
    value["constraints"]["budget_gbp"] = "0"
    report = compare_freight_alternatives(PlanningScenario.model_validate_json(json.dumps(value)))
    assert all(not row["feasible"] and row["failure_code"] for row in report["rows"])


def test_cli_comparison_is_opt_in_and_protects_evidence(monkeypatch, tmp_path, scenario):
    from app.experiments import freight_continuous_analytics
    from app.experiments.cli import main

    attempt, output = tmp_path / "attempt", tmp_path / "output"
    attempt.mkdir()
    output.mkdir()
    (attempt / "planning-scenario.json").write_text(scenario.model_dump_json())
    monkeypatch.setattr(freight_continuous_analytics, "analyze_continuous", lambda *a, **kw: {})
    args = ["analyze-continuous-freight", str(attempt), "--output", str(output)]
    assert main(args) == 0
    destination = output / "planning-alternatives.json"
    assert not destination.exists()
    assert main([*args, "--compare-planning"]) == 0
    report = json.loads(destination.read_text())
    assert report["rows"][0]["served_planning_units"] == 60
    destination.unlink()
    destination.symlink_to(attempt / "planning-scenario.json")
    assert main([*args, "--compare-planning"]) == 1
    assert (attempt / "planning-scenario.json").read_text() == scenario.model_dump_json()
