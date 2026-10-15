"""Portable controlled replanning regression; test doubles never establish native proof."""

import json
import socket
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest

from app.experiments.freight_evaluation import FreightEvaluation
from app.experiments.freight_history import FreightHistory
from app.experiments.freight_network import evaluate_freight_network
from app.planning.canonical import canonical_bytes, plan_hash
from app.planning.domain import PlanningScenario
from app.planning.optimizer import optimize_candidate_network
from app.planning.realized import ArtifactReference


@pytest.fixture(autouse=True)
def no_native(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("feedback comparison attempted a native process or connection")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.fixture
def scenario():
    return PlanningScenario.model_validate_json(
        (Path(__file__).parent / "fixtures/multi_service/scenario.json").read_bytes()
    )


@pytest.fixture
def feedback_history(scenario, tmp_path, monkeypatch):
    from app.planning import feedback

    plan = optimize_candidate_network(scenario).plan
    report = evaluate_freight_network(plan, scenario)
    metric_rows = []
    for metric in report.metrics:
        if metric.name == "infrastructure_capex":
            assert metric.planned is not None
            metric = metric.model_copy(
                update={
                    "actual": metric.planned * 2,
                    "comparison": "comparable",
                    "difference": metric.planned,
                }
            )
        elif metric.name == "delivery_revenue":
            metric = metric.model_copy(update={"actual": Decimal(0)})
        metric_rows.append(metric)
    metrics = tuple(metric_rows)
    receipt = ArtifactReference(reference="receipt.json", sha256="1" * 64)
    report = report.model_copy(
        update={
            "classification": "NATIVE_MULTI_SERVICE_EVALUATION",
            "native_execution_ready": True,
            "verified_service_count": len(plan.routes),
            "metrics": metrics,
            "evidence_refs": (receipt,),
        }
    )
    evaluation = FreightEvaluation(
        run_name="controlled-verifier-double",
        attempt=1,
        mode="planner-network",
        status="verified-delivery",
        reason=None,
        source_directory=str(tmp_path / "controlled-source"),
        receipt=receipt,
        artifact_manifest=ArtifactReference(reference="artifact-manifest.sha256", sha256="2" * 64),
        result=ArtifactReference(reference="result.json", sha256="3" * 64),
        native_plan_digest=None,
        execution_plan_digest=plan_hash(plan),
        cohort_digest="4" * 64,
        cohort_definition={},
        metrics=metrics,
        network_report=report.model_dump(mode="json"),
        findings=(),
        limitations=("CONTROLLED verifier double; no native evidence is fabricated.",),
    )
    history_path = tmp_path / "history.sqlite"
    history = FreightHistory(history_path)
    history.add([evaluation])
    history.close()
    monkeypatch.setattr(feedback, "evaluate_freight", lambda directory: evaluation)
    return history_path, evaluation


def test_default_identity_and_identical_constraints(scenario, feedback_history):
    from app.planning.feedback import compare_feedback_scenarios

    history_path, evaluation = feedback_history
    before = scenario.model_dump_json()
    baseline = optimize_candidate_network(scenario)
    comparison = compare_feedback_scenarios(scenario, history_path, evaluation.history_key)
    rows = comparison["scenarios"]
    assert rows[0]["plan_digest"] == plan_hash(baseline.plan)
    assert scenario.model_dump_json() == before
    assert plan_hash(optimize_candidate_network(scenario).plan) == plan_hash(baseline.plan)
    for row in rows:
        variant = PlanningScenario.model_validate_json(json.dumps(row["scenario"]))
        assert variant.constraints == scenario.constraints
        assert variant.cargo_demands == scenario.cargo_demands
        assert variant.fleet_options == scenario.fleet_options
        assert len(variant.infrastructure_candidates) == len(scenario.infrastructure_candidates)
    assert rows[0]["expected_spending_gbp"] == "2580"
    assert rows[1]["expected_spending_gbp"] == "3160.00"
    assert comparison["evidence"]["history_key"] == evaluation.history_key
    assert comparison["evidence"]["execution_plan_digest"] == evaluation.execution_plan_digest
    assert comparison["evidence"]["receipt"] == evaluation.receipt.model_dump(mode="json")
    text = " ".join(comparison["limitations"])
    assert "backlog" in text and "OPEX" in text and "statistically calibrated" in text
    assert "does not demonstrate optimization improvement" in text


def test_cost_stress_changes_selection_and_baseline_feasibility(scenario, feedback_history):
    from app.planning.feedback import compare_feedback_scenarios

    history_path, evaluation = feedback_history
    scenario = scenario.model_copy(
        update={
            "constraints": scenario.constraints.model_copy(update={"budget_gbp": Decimal(3000)})
        }
    )
    rows = compare_feedback_scenarios(scenario, history_path, evaluation.history_key)["scenarios"]
    assert [len(row["selected_services"]) for row in rows] == [2, 1, 1]
    assert [row["baseline_selection_budget_feasible"] for row in rows] == [True, False, False]
    assert [row["fleet_capacity_cargo_units"] for row in rows] == [120, 60, 60]
    assert all(Decimal(row["expected_spending_gbp"]) <= 3000 for row in rows)
    tight = scenario.model_copy(
        update={
            "constraints": scenario.constraints.model_copy(update={"budget_gbp": Decimal(1300)})
        }
    )
    rows = compare_feedback_scenarios(tight, history_path, evaluation.history_key)["scenarios"]
    assert [row["feasible"] for row in rows] == [True, False, False]
    assert rows[1]["selected_services"] == []
    assert rows[1]["expected_spending_gbp"] is None


def test_shared_assets_charged_once_under_every_cost_assumption(scenario, feedback_history):
    from app.planning.feedback import compare_feedback_scenarios

    history_path, evaluation = feedback_history
    first = scenario.cargo_demands[0]
    selection = scenario.constraints.network_selection
    resource = next(r for r in selection.service_resources if r.demand_id == first.demand_id)
    shared = scenario.model_copy(
        update={
            "cargo_demands": (first, first.model_copy(update={"demand_id": "second-batch"})),
            "constraints": scenario.constraints.model_copy(
                update={
                    "network_selection": selection.model_copy(
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
    rows = compare_feedback_scenarios(shared, history_path, evaluation.history_key)["scenarios"]
    assert [Decimal(row["infrastructure_spending_gbp"]) for row in rows] == [290, 580, 870]
    assert all(len(row["selected_services"]) == 2 for row in rows)
    assert [Decimal(row["baseline_selection_spending_gbp"]) for row in rows] == [2290, 2580, 2870]


def test_history_mismatch_and_replayed_evidence_tampering_rejected(
    scenario, feedback_history, monkeypatch
):
    from app.planning import feedback

    history_path, evaluation = feedback_history
    with pytest.raises(ValueError, match="one history entry"):
        feedback.compare_feedback_scenarios(scenario, history_path, "0" * 64)
    monkeypatch.setattr(
        feedback,
        "evaluate_freight",
        lambda directory: evaluation.model_copy(update={"execution_plan_digest": "0" * 64}),
    )
    with pytest.raises(ValueError, match="replay differs"):
        feedback.compare_feedback_scenarios(scenario, history_path, evaluation.history_key)


def test_stored_history_tampering_rejected(scenario, feedback_history):
    from sqlalchemy import text

    from app.planning.feedback import compare_feedback_scenarios

    history_path, evaluation = feedback_history
    history = FreightHistory(history_path)
    with history.engine.begin() as connection:
        connection.execute(
            text("UPDATE freight_run_history SET evaluation_digest = :digest"), {"digest": "0" * 64}
        )
    history.close()
    with pytest.raises(ValueError, match="stored freight evaluation digest mismatch"):
        compare_feedback_scenarios(scenario, history_path, evaluation.history_key)


def test_controlled_unverified_report_cannot_inform_feedback(scenario):
    from app.planning.feedback import compare_verified_feedback

    report = evaluate_freight_network(optimize_candidate_network(scenario).plan, scenario)
    with pytest.raises(ValueError, match="verified native network"):
        compare_verified_feedback(scenario, report)


@pytest.mark.parametrize("protected", ["history", "scenario", "evidence"])
def test_cli_symlink_outputs_cannot_overwrite_inputs(
    scenario, feedback_history, tmp_path, protected
):
    from app.planning.network_cli import main

    history_path, evaluation = feedback_history
    scenario_path = tmp_path / "scenario.json"
    scenario_path.write_text(scenario.model_dump_json())
    source = Path(evaluation.source_directory)
    source.mkdir()
    retained = source / "sentinel.json"
    retained.write_text("retained immutable bytes")
    output = tmp_path / "output"
    output.mkdir()
    targets = {"history": history_path, "scenario": scenario_path, "evidence": retained}
    target = targets[protected]
    original = target.read_bytes()
    (output / "planning-comparison.json").symlink_to(target)
    with pytest.raises(SystemExit) as error:
        main(
            [
                str(scenario_path),
                "--output",
                str(output),
                "--feedback-history",
                str(history_path),
                "--feedback-run",
                evaluation.history_key,
            ]
        )
    assert error.value.code == 2
    assert target.read_bytes() == original
    assert not (output / "execution-plan.json").exists()


def test_cli_writes_comparison_json_and_existing_html(scenario, feedback_history, tmp_path, capsys):
    from app.planning.network_cli import main

    history_path, evaluation = feedback_history
    scenario_path = tmp_path / "scenario.json"
    scenario_path.write_text(scenario.model_dump_json())
    output = tmp_path / "output"
    assert (
        main(
            [
                str(scenario_path),
                "--output",
                str(output),
                "--feedback-history",
                str(history_path),
                "--feedback-run",
                evaluation.history_key,
            ]
        )
        == 0
    )
    comparison = json.loads((output / "planning-comparison.json").read_text())
    assert len(comparison["scenarios"]) == 3
    assert "Controlled P05 feedback comparison" in (output / "charts.html").read_text()
    assert "offline report only" in capsys.readouterr().out
    assert (output / "execution-plan.json").read_bytes().strip() == canonical_bytes(
        optimize_candidate_network(scenario).plan
    )


def test_cli_reports_every_scenario_when_baseline_infeasible(scenario, feedback_history, tmp_path):
    from app.planning.network_cli import main

    history_path, evaluation = feedback_history
    scenario = scenario.model_copy(
        update={"constraints": scenario.constraints.model_copy(update={"budget_gbp": Decimal(1)})}
    )
    scenario_path = tmp_path / "infeasible.json"
    scenario_path.write_text(scenario.model_dump_json())
    output = tmp_path / "output"
    assert (
        main(
            [
                str(scenario_path),
                "--output",
                str(output),
                "--feedback-history",
                str(history_path),
                "--feedback-run",
                evaluation.history_key,
            ]
        )
        == 0
    )
    comparison = json.loads((output / "planning-comparison.json").read_text())
    assert [row["feasible"] for row in comparison["scenarios"]] == [False, False, False]
    assert all(row["expected_spending_gbp"] is None for row in comparison["scenarios"])
    assert not (output / "execution-plan.json").exists()


def test_default_cli_retains_original_optimizer_identity(scenario, tmp_path):
    from app.planning.network_cli import main

    scenario_path = tmp_path / "scenario.json"
    scenario_path.write_text(scenario.model_dump_json())
    output = tmp_path / "baseline"
    assert main([str(scenario_path), "--output", str(output)]) == 0
    assert (output / "execution-plan.json").read_bytes().strip() == canonical_bytes(
        optimize_candidate_network(scenario).plan
    )
    assert not (output / "planning-comparison.json").exists()
    assert not (output / "charts.html").exists()


def test_infeasible_cli_rejects_stale_baseline_artifacts(scenario, feedback_history, tmp_path):
    from app.planning.network_cli import main

    history_path, evaluation = feedback_history
    scenario_path = tmp_path / "scenario.json"
    scenario_path.write_text(scenario.model_dump_json())
    output = tmp_path / "output"
    assert main([str(scenario_path), "--output", str(output)]) == 0
    prior = (output / "execution-plan.json").read_bytes()
    infeasible = scenario.model_copy(
        update={"constraints": scenario.constraints.model_copy(update={"budget_gbp": Decimal(1)})}
    )
    scenario_path.write_text(infeasible.model_dump_json())
    with pytest.raises(SystemExit) as error:
        main(
            [
                str(scenario_path),
                "--output",
                str(output),
                "--feedback-history",
                str(history_path),
                "--feedback-run",
                evaluation.history_key,
            ]
        )
    assert error.value.code == 2
    assert (output / "execution-plan.json").read_bytes() == prior
    assert not (output / "planning-comparison.json").exists()


def test_backlog_observations_do_not_change_demand_supply_or_revenue(scenario, feedback_history):
    from app.experiments.freight_evaluation import FreightMetric
    from app.experiments.freight_network import NetworkEvaluation
    from app.planning.feedback import compare_verified_feedback

    _, evaluation = feedback_history
    report = NetworkEvaluation.model_validate_json(json.dumps(evaluation.network_report))
    comparison = compare_verified_feedback(scenario, report)
    services = tuple(
        service.model_copy(
            update={
                "metrics": service.metrics
                + (
                    FreightMetric(
                        name="source_waiting",
                        unit="cargo_units",
                        scope="source_station",
                        actual=Decimal(waiting),
                        provenance="Controlled observed backlog",
                    ),
                )
            }
        )
        for service, waiting in zip(report.services, (54, 42), strict=True)
    )
    backlog = report.model_copy(update={"services": services})
    assert compare_verified_feedback(scenario, backlog) == comparison
    assert all(
        row["scenario"]["cargo_demands"] == scenario.model_dump(mode="json")["cargo_demands"]
        for row in comparison["scenarios"]
    )
    unknowns = {metric.name: metric.actual for metric in report.metrics}
    assert unknowns["operating_costs"] is None
    assert unknowns["net_return"] is None
