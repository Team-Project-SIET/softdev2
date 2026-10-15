"""Matched reporting preserves unknown actuals and admits independently verified evidence."""

import json
from pathlib import Path

import pytest

from app.experiments.feedback_comparison import write_comparison
from app.planning.domain import PlanningScenario
from app.planning.optimizer import optimize_candidate_network


@pytest.fixture
def selection():
    scenario = PlanningScenario.model_validate_json(
        (Path(__file__).parent / "fixtures/multi_service/scenario.json").read_bytes()
    )
    return scenario, optimize_candidate_network(scenario).plan


def test_identical_selection_reports_unknown_actuals(tmp_path, selection):
    scenario, plan = selection
    report = write_comparison(
        tmp_path,
        {"plans_differ": False, "source": "controlled fixture"},
        plan,
        scenario,
        plan,
        scenario,
    )
    assert (
        report["variants"]["baseline"]["selected_plan_digest"]
        == report["variants"]["feedback"]["selected_plan_digest"]
    )
    for variant in report["variants"].values():
        assert variant["status"] == "not-executed"
        assert variant["evidence"] is None
        assert variant["roi"] is None
        assert all(m["actual"] is None for m in variant["metrics"])
    assert all(d["actual"] is None for d in report["feedback_minus_baseline"].values())
    assert (
        json.loads((tmp_path / "comparison.json").read_text())["variants"]["baseline"]["roi"]
        is None
    )
    html = (tmp_path / "charts.html").read_text()
    assert "unknown" in html and "Estimation error" in html and "ROI" in html


def test_same_evidence_directory_rejected_before_read(tmp_path, selection):
    scenario, plan = selection
    with pytest.raises(ValueError, match="verified clone provenance"):
        write_comparison(
            tmp_path,
            {},
            plan,
            scenario,
            plan,
            scenario,
            {"baseline": tmp_path, "feedback": tmp_path / "."},
        )


def test_output_preserves_existing_report(tmp_path, selection):
    scenario, plan = selection
    (tmp_path / "comparison.json").write_text("immutable")
    with pytest.raises(ValueError, match="already exists"):
        write_comparison(tmp_path, {}, plan, scenario, plan, scenario)
    assert (tmp_path / "comparison.json").read_text() == "immutable"


def test_output_cannot_be_inside_protected_evidence(tmp_path, selection):
    scenario, plan = selection
    with pytest.raises(ValueError, match="protected evidence"):
        write_comparison(
            tmp_path / "report",
            {"protected_directories": [str(tmp_path)]},
            plan,
            scenario,
            plan,
            scenario,
        )
