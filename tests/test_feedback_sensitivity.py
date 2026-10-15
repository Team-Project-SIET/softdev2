"""Offline breakpoint regressions using existing CONTROLLED feedback fixtures."""

import hashlib
import json
import socket
import subprocess
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_feedback_experiment import _identity_placeholders
from test_planning_feedback import feedback_history as controlled_feedback_history

from app.experiments import feedback_experiment as experiment
from app.experiments.feedback_sensitivity import analyze_sensitivity
from app.planning.canonical import plan_hash
from app.planning.domain import PlanningScenario, ResourceLimit
from app.planning.feedback import compare_feedback_scenarios
from app.planning.optimizer import OptimizerFailure, optimize_candidate_network


@pytest.fixture(autouse=True)
def forbid_native(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("controlled sensitivity launched a process or opened a connection")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.fixture
def scenario():
    return PlanningScenario.model_validate_json(
        (Path(__file__).parent / "fixtures/multi_service/scenario.json").read_bytes()
    )


@pytest.fixture(name="feedback_history")
def retained_controlled_history(scenario, tmp_path, monkeypatch):
    return controlled_feedback_history.__wrapped__(scenario, tmp_path, monkeypatch)


def variants(scenario, feedback_history):
    history, evaluation = feedback_history
    comparison = compare_feedback_scenarios(scenario, history, evaluation.history_key)
    return {
        row["name"]: PlanningScenario.model_validate_json(json.dumps(row["scenario"]))
        for row in comparison["scenarios"]
    }


def at_budget(report, budget):
    return next(row["variants"] for row in report["rows"] if Decimal(row["budget_gbp"]) == budget)


def test_exact_budget_boundaries_distinguish_feasibility_and_service_changes(
    scenario, feedback_history
):
    report = analyze_sensitivity(variants(scenario, feedback_history))
    # These amounts are derived from the retained controlled fixture (290 infrastructure,
    # two 500 vehicles); feedback_history supplies the existing doubled-cost stress.
    first = scenario.cargo_demands[0]
    resource = scenario.constraints.network_selection.service_resources[0]
    costs = {c.candidate_id: c.estimated_build_cost_gbp for c in scenario.infrastructure_candidates}
    infrastructure = sum(costs[c] for c in resource.candidate_ids)
    fleet = scenario.fleet_options[0].vehicle
    purchase = (
        (first.quantity + fleet.capacity_cargo_units - 1) // fleet.capacity_cargo_units
    ) * fleet.purchase_cost_gbp
    baseline_first, feedback_first = infrastructure + purchase, infrastructure * 2 + purchase
    assert at_budget(report, baseline_first)["baseline"]["feasible"]
    assert not at_budget(report, baseline_first)["observed-error"]["feasible"]
    assert at_budget(report, feedback_first)["observed-error"]["feasible"]
    both = at_budget(report, baseline_first * 2)
    assert len(both["baseline"]["selected_services"]) == 2
    assert len(both["observed-error"]["selected_services"]) == 1
    assert len(at_budget(report, feedback_first * 2)["observed-error"]["selected_services"]) == 2
    assert report["decision_differences_found"]
    assert report["feasibility_intervals"]
    assert all(
        i["baseline"]["feasible"] and i["feedback"]["feasible"]
        for i in report["decision_intervals"]
    )
    assert all(
        i["baseline"]["feasible"] != i["feedback"]["feasible"]
        for i in report["feasibility_intervals"]
    )
    below_first = max(Decimal(b) for b in report["budget_grid"] if Decimal(b) < baseline_first)
    assert not at_budget(report, below_first)["baseline"]["feasible"]


def test_every_sample_matches_real_p05_and_all_reported_slacks(scenario, feedback_history):
    scenarios = variants(scenario, feedback_history)
    report = analyze_sensitivity(scenarios)
    for row in report["rows"]:
        budget = Decimal(row["budget_gbp"])
        for name, summary in row["variants"].items():
            original = scenarios[name]
            changed = original.model_copy(
                update={
                    "constraints": original.constraints.model_copy(update={"budget_gbp": budget})
                }
            )
            if not summary["feasible"]:
                with pytest.raises(OptimizerFailure):
                    optimize_candidate_network(changed)
                continue
            result = optimize_candidate_network(changed)
            ids = sorted(a.demand_id for r in result.plan.routes for a in r.cargo_assignments)
            assert summary["selected_services"] == ids
            assert summary["independently_validated"]
            assert (
                Decimal(summary["estimated_capex_gbp"])
                == result.metrics.infrastructure_spend_gbp
                + result.metrics.vehicle_purchase_cost_gbp
            )
            assert Decimal(summary["slack"]["budget_gbp"]) == budget - Decimal(
                summary["estimated_capex_gbp"]
            )
            assert (
                summary["slack"]["vehicles"]
                == original.constraints.network_selection.max_vehicles - summary["vehicles"]
            )
            assert all(s["quantity"] >= 0 for s in summary["slack"]["supplies"])
            assert all(s >= 0 for s in summary["slack"]["resources"].values())
            assert (
                summary["capacity_cargo_units"]
                == summary["vehicles"] * original.fleet_options[0].vehicle.capacity_cargo_units
            )
            assert summary["served_demand_units"] == sum(
                d.quantity for d in original.cargo_demands if d.demand_id in ids
            )
            assert summary["objective"] == {
                "maximize_served_cargo_units": summary["served_demand_units"],
                "minimize_capex_gbp": summary["estimated_capex_gbp"],
            }


def test_zero_uplift_exhaustively_demonstrates_no_differences(scenario):
    report = analyze_sensitivity({"baseline": scenario, "observed-error": scenario})
    assert report["bounds"]["exhaustive"]
    assert report["decision_differences_found"] is False
    assert report["decision_intervals"] == report["feasibility_intervals"] == []
    assert all(
        row["variants"]["baseline"] == row["variants"]["observed-error"] for row in report["rows"]
    )


def test_shared_assets_are_charged_once_for_every_combination_and_variant(
    scenario, feedback_history
):
    first = scenario.cargo_demands[0]
    network = scenario.constraints.network_selection
    resource = next(r for r in network.service_resources if r.demand_id == first.demand_id)
    shared = scenario.model_copy(
        update={
            "cargo_demands": (first, first.model_copy(update={"demand_id": "second-batch"})),
            "constraints": scenario.constraints.model_copy(
                update={
                    "network_selection": network.model_copy(
                        update={
                            "service_resources": (
                                resource,
                                resource.model_copy(update={"demand_id": "second-batch"}),
                            )
                        }
                    )
                }
            ),
        }
    )
    scenarios = variants(shared, feedback_history)
    report = analyze_sensitivity(scenarios)
    for name, inventory in report["scenarios"].items():
        costs = {
            c.candidate_id: c.estimated_build_cost_gbp
            for c in scenarios[name].infrastructure_candidates
        }
        two = [
            row for row in inventory["eligible_combinations"] if len(row["selected_services"]) == 2
        ]
        assert two
        for row in two:
            ids = row["selected_candidate_ids"]
            assert len(ids) == len(set(ids)) == len(resource.candidate_ids)
            assert Decimal(row["infrastructure_capex_gbp"]) == sum(costs[c] for c in ids)
            assert Decimal(row["estimated_capex_gbp"]) == Decimal(
                row["infrastructure_capex_gbp"]
            ) + Decimal(row["vehicle_purchase_gbp"])


def test_input_and_default_plan_are_unchanged_and_result_deterministic(scenario, feedback_history):
    scenarios = variants(scenario, feedback_history)
    before = {name: value.model_dump_json() for name, value in scenarios.items()}
    default = plan_hash(optimize_candidate_network(scenario).plan)
    first = analyze_sensitivity(scenarios)
    assert analyze_sensitivity(scenarios) == first
    assert before == {name: value.model_dump_json() for name, value in scenarios.items()}
    assert plan_hash(optimize_candidate_network(scenario).plan) == default
    assumptions = " ".join(first["assumptions"])
    assert "retrospective feedback, not independent validation" in assumptions
    assert "OPEX" in assumptions and "unknown" in assumptions
    assert first["classification"] == "CONTROLLED_FEEDBACK_DECISION_SENSITIVITY"
    assert first["native_launches"] == 0


def test_bounded_search_fails_instead_of_truncating(scenario):
    with pytest.raises(ValueError, match="combinations exceed bound"):
        analyze_sensitivity({"baseline": scenario, "observed-error": scenario}, max_combinations=1)


def test_non_cost_inputs_cannot_change_between_variants(scenario):
    altered = scenario.model_copy(
        update={
            "cargo_demands": (
                scenario.cargo_demands[0].model_copy(update={"quantity": 1}),
                *scenario.cargo_demands[1:],
            )
        }
    )
    with pytest.raises(ValueError, match="cost|identical|nonbudget|matched"):
        analyze_sensitivity({"baseline": scenario, "observed-error": altered})


def test_nonbudget_resource_limits_exclude_combinations_and_report_exact_slack(scenario):
    network = scenario.constraints.network_selection
    resource_id = next(
        c.candidate_id for c in scenario.infrastructure_candidates if c.kind.value == "depot"
    )
    constrained = scenario.model_copy(
        update={
            "constraints": scenario.constraints.model_copy(
                update={
                    "network_selection": network.model_copy(
                        update={
                            "resource_limits": (
                                ResourceLimit(candidate_id=resource_id, max_vehicles=1),
                            )
                        }
                    )
                }
            )
        }
    )
    report = analyze_sensitivity({"baseline": constrained, "observed-error": constrained})
    inventory = report["scenarios"]["baseline"]
    assert inventory["rejected_nonbudget_constraints"] > 0
    assert all(
        resource_id not in row["selected_candidate_ids"]
        for row in inventory["eligible_combinations"]
    )
    for row in report["rows"]:
        summary = row["variants"]["baseline"]
        if summary["feasible"]:
            assert summary["slack"]["resources"] == {resource_id: 1}


def test_absence_of_eligible_positive_services_is_explicit(scenario):
    network = scenario.constraints.network_selection
    constrained = scenario.model_copy(
        update={
            "constraints": scenario.constraints.model_copy(
                update={"network_selection": network.model_copy(update={"max_vehicles": 1})}
            )
        }
    )
    report = analyze_sensitivity({"baseline": constrained, "observed-error": constrained})
    assert report["scenarios"]["baseline"]["eligible_combinations"] == []
    assert not report["decision_differences_found"]
    assert all(
        not variant["feasible"] for row in report["rows"] for variant in row["variants"].values()
    )


def test_reproducible_cli_embeds_sensitivity_in_existing_reports(
    scenario, tmp_path, monkeypatch, capsys
):
    source = tmp_path / "retained"
    source.mkdir()
    _identity_placeholders(source)
    plan = optimize_candidate_network(scenario).plan
    (source / "planning-scenario.json").write_text(scenario.model_dump_json())
    (source / "execution-plan.json").write_text(plan.model_dump_json())
    digest = hashlib.sha256((source / "before.sav").read_bytes()).hexdigest()
    for name, value in (
        ("prepared-source-links.json", {"original_save_digest": digest}),
        ("runtime-identity.json", {"welcome": {"seed": 1}}),
        ("graphics-identity.json", {}),
        ("planning-policy.json", {}),
    ):
        (source / name).write_text(json.dumps(value))
    monkeypatch.setattr(
        experiment,
        "evaluate_freight",
        lambda path: SimpleNamespace(
            status="verified-delivery", network_report={}, model_dump=lambda **kwargs: {}
        ),
    )
    row = {
        "feasible": True,
        "plan": plan.model_dump(mode="json"),
        "scenario": scenario.model_dump(mode="json"),
        "infrastructure_cost_multiplier": "1",
    }
    monkeypatch.setattr(
        experiment,
        "compare_feedback_scenarios",
        lambda *args: {
            "scenarios": [dict(row, name="baseline"), dict(row, name="observed-error")],
            "evidence": {"evidence_directory": str(source)},
            "observed_infrastructure_error_gbp": "0",
            "observed_planned_infrastructure_gbp": "1",
            "observed_actual_infrastructure_gbp": "1",
            "limitations": [],
        },
    )
    output = tmp_path / "sensitivity"
    args = [
        str(source),
        "--feedback-history",
        str(tmp_path / "history.sqlite"),
        "--feedback-run",
        "CONTROLLED",
        "--output",
        str(output),
        "--sensitivity",
    ]
    assert experiment.main(args) == 0
    assert "FEEDBACK DECISION SENSITIVITY COMPLETE" in capsys.readouterr().out
    manifest = json.loads((output / "planning-manifest.json").read_text())
    comparison = json.loads((output / "comparison.json").read_text())
    assert manifest["sensitivity"] == comparison["sensitivity"]
    assert not comparison["sensitivity"]["decision_differences_found"]
    assert manifest["native_launches"] == 0
    html = (output / "charts.html").read_text()
    assert "Controlled decision sensitivity" in html
    assert "<svg" in html and "retrospective" in html
    assert hashlib.sha256((source / "before.sav").read_bytes()).hexdigest() == digest
    default_output = tmp_path / "default"
    assert experiment.main(args[:-2] + [str(default_output)]) == 0
    default = json.loads((default_output / "planning-manifest.json").read_text())
    assert "sensitivity" not in default
