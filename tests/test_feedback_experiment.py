"""Controlled experiment-validity guards; fixtures never establish native proof."""

import socket
import subprocess
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.experiments import feedback_experiment as experiment
from app.planning.domain import PlanningScenario
from app.planning.optimizer import optimize_candidate_network


@pytest.fixture(autouse=True)
def forbid_native(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("offline matched decision experiment launched or connected")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.fixture
def scenario():
    return PlanningScenario.model_validate_json(
        (Path(__file__).parent / "fixtures/multi_service/scenario.json").read_bytes()
    )


def test_semantic_identity_ignores_cost_only_and_input_digest_changes(scenario):
    baseline = optimize_candidate_network(scenario).plan
    uplifted = scenario.model_copy(
        update={
            "infrastructure_candidates": tuple(
                candidate.model_copy(
                    update={
                        "estimated_build_cost_gbp": candidate.estimated_build_cost_gbp
                        * Decimal("1.2")
                    }
                )
                for candidate in scenario.infrastructure_candidates
            )
        }
    )
    feedback = optimize_candidate_network(uplifted).plan
    assert baseline.planner_inputs_digest != feedback.planner_inputs_digest
    assert baseline.infrastructure != feedback.infrastructure
    assert experiment.semantic_plan(baseline) == experiment.semantic_plan(feedback)


def test_semantic_identity_detects_actual_selection_difference(scenario):
    baseline = optimize_candidate_network(scenario).plan
    tight = scenario.model_copy(
        update={
            "constraints": scenario.constraints.model_copy(update={"budget_gbp": Decimal("1300")})
        }
    )
    different = optimize_candidate_network(tight).plan
    assert experiment.semantic_plan(baseline) != experiment.semantic_plan(different)


def _identity_placeholders(source):
    for name in (
        "before.sav",
        "qualified.sav",
        "planning-scenario.json",
        "planning-policy.json",
        "execution-plan.json",
        "world-planning-observation.json",
        "prepared-source-links.json",
        "runtime-identity.json",
        "graphics-identity.json",
        "PRELAUNCH.json",
        "receipt.json",
    ):
        (source / name).write_bytes(b"CONTROLLED identity placeholder")


@pytest.mark.parametrize("kind", ["existing", "inside-source", "history"])
def test_output_guard_precedes_receipt_replay(tmp_path, monkeypatch, kind):
    source = tmp_path / "retained"
    source.mkdir()
    history = tmp_path / "history.sqlite"
    history.write_bytes(b"controlled history sentinel")
    outputs = {"existing": source, "inside-source": source / "new", "history": history}
    monkeypatch.setattr(
        experiment, "evaluate_freight", lambda path: pytest.fail("replayed before guard")
    )
    with pytest.raises(ValueError, match="fresh directory"):
        experiment.prepare_experiment(source, history, "controlled", outputs[kind])
    assert history.read_bytes() == b"controlled history sentinel"


def test_unverified_source_rejected_without_output(tmp_path, monkeypatch):
    source = tmp_path / "retained"
    source.mkdir()
    _identity_placeholders(source)
    output = tmp_path / "experiment"
    monkeypatch.setattr(
        experiment,
        "evaluate_freight",
        lambda path: SimpleNamespace(status="failed", network_report=None),
    )
    with pytest.raises(ValueError, match="independently verified"):
        experiment.prepare_experiment(source, tmp_path / "history.sqlite", "controlled", output)
    assert not output.exists()


def test_feedback_evidence_directory_is_protected(tmp_path, monkeypatch, scenario):
    """Cross-world feedback must not permit writes under its retained evidence root."""
    source = tmp_path / "planning-source"
    source.mkdir()
    _identity_placeholders(source)
    other_evidence = tmp_path / "feedback-evidence"
    other_evidence.mkdir()
    plan = optimize_candidate_network(scenario).plan
    (source / "planning-scenario.json").write_text(scenario.model_dump_json())
    (source / "execution-plan.json").write_text(plan.model_dump_json())
    monkeypatch.setattr(
        experiment,
        "evaluate_freight",
        lambda path: SimpleNamespace(status="verified-delivery", network_report={}),
    )
    row = {"feasible": True, "plan": plan.model_dump(mode="json")}
    monkeypatch.setattr(
        experiment,
        "compare_feedback_scenarios",
        lambda *args: {
            "scenarios": [dict(row, name="baseline"), dict(row, name="observed-error")],
            "evidence": {"evidence_directory": str(other_evidence)},
        },
    )
    output = other_evidence / "new-experiment"
    with pytest.raises(ValueError, match="retained feedback evidence"):
        experiment.prepare_experiment(source, tmp_path / "history.sqlite", "controlled", output)
    assert not output.exists()


def test_json_comparison_rows_reach_complete_report(tmp_path, monkeypatch, scenario):
    """Real comparison rows contain JSON arrays despite strict tuple domain contracts."""
    import hashlib
    import json

    source = tmp_path / "source"
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
    retained = SimpleNamespace(
        status="verified-delivery", network_report={}, model_dump=lambda **kwargs: {}
    )
    monkeypatch.setattr(experiment, "evaluate_freight", lambda path: retained)
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
    output = tmp_path / "experiment"
    manifest = experiment.prepare_experiment(source, tmp_path / "history.sqlite", "test", output)
    assert manifest["status"] == "MATCHED FEEDBACK EXPERIMENT COMPLETE"
    assert manifest["plans_differ"] is False
    assert manifest["native_launches"] == 0
    assert (output / "comparison.json").is_file()
    assert (output / "charts.html").is_file()
    assert (output / "baseline-scenario.json").is_file()
    assert (output / "feedback-scenario.json").is_file()
    assert (output / "baseline-plan.json").read_bytes() == (
        output / "feedback-plan.json"
    ).read_bytes()
    assert hashlib.sha256((source / "before.sav").read_bytes()).hexdigest() == digest
    for name, expected in manifest["matched_inputs"]["verified_source_files"].items():
        assert hashlib.sha256((source / name).read_bytes()).hexdigest() == expected


def test_json_plan_requires_json_mode_parser(scenario):
    """Capture the old Python-mode parser failure at the exact JSON row boundary."""
    import json

    from pydantic import ValidationError

    from app.planning.domain import ExecutionPlan

    plan = optimize_candidate_network(scenario).plan
    row = plan.model_dump(mode="json")
    with pytest.raises(ValidationError, match="tuple_type"):
        ExecutionPlan.model_validate(row)
    assert ExecutionPlan.model_validate_json(json.dumps(row)) == plan
