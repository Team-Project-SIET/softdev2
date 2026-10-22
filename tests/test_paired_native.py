"""Controlled paired admission; optimizer selection never proves native feasibility."""

import json
import socket
import subprocess
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_freight_network import packages  # noqa: F401
from test_paired_source import source as controlled_source  # noqa: F401

from app.experiments import paired_native as paired
from app.planning.domain import PlanningScenario
from app.planning.optimizer import optimize_candidate_network
from app.planning.p08_adapter import adapt_planning_facts
from app.planning.p08_network import generate_freight_network
from app.simulation.openttd.freight_planning import compile_freight_network


@pytest.fixture(autouse=True)
def no_native(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("paired preparation launched or connected")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


@pytest.fixture
def selections():
    original = PlanningScenario.model_validate_json(
        Path("tests/fixtures/multi_service/scenario.json").read_bytes()
    )
    budget = Decimal("3000")
    baseline = original.model_copy(
        update={"constraints": original.constraints.model_copy(update={"budget_gbp": budget})}
    )
    feedback = baseline.model_copy(
        update={
            "infrastructure_candidates": tuple(
                c.model_copy(update={"estimated_build_cost_gbp": c.estimated_build_cost_gbp * 2})
                for c in baseline.infrastructure_candidates
            )
        }
    )
    scenarios = {"baseline": baseline, "feedback": feedback}
    plans = {name: optimize_candidate_network(s).plan for name, s in scenarios.items()}
    return scenarios, plans, budget


def test_real_p05_diverges_without_forced_selection_and_independent_validation(selections):
    scenarios, plans, budget = selections
    result = paired.validate_variants(scenarios, plans, budget)
    assert len(plans["baseline"].routes) == 2
    assert len(plans["feedback"].routes) == 1
    assert all(row["structural_valid"] for row in result.values())
    assert all(not row["native_ready"] for row in result.values())
    assert all(Decimal(row["estimated_capex_gbp"]) <= budget for row in result.values())
    assert all(any("funds unavailable" in b for b in row["blockers"]) for row in result.values())


def test_historical_capex_excess_is_explicit_and_never_relaxes_cap(selections):
    scenarios, plans, budget = selections
    result = paired.validate_variants(scenarios, plans, budget, Decimal("4101"))
    assert any("exceeds hard cap" in b for b in result["baseline"]["blockers"])
    assert not any("exceeds hard cap" in b for b in result["feedback"]["blockers"])
    assert all(s.constraints.budget_gbp == budget for s in scenarios.values())


@pytest.mark.parametrize(
    "budget",
    [
        Decimal("0"),
        Decimal("-1"),
        Decimal("19100.99"),
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
    ],
)
def test_currency_caps_require_positive_integer_units(selections, budget):
    scenarios, plans, _ = selections
    with pytest.raises(ValueError, match="positive integer GBP"):
        paired.validate_variants(scenarios, plans, budget)


def test_one_invalid_variant_does_not_hide_other_validation(selections):
    scenarios, plans, budget = selections
    plans["baseline"] = plans["baseline"].model_copy(update={"world_fingerprint": "0" * 64})
    result = paired.validate_variants(scenarios, plans, budget)
    assert not result["baseline"]["structural_valid"]
    assert result["feedback"]["structural_valid"]
    assert result["baseline"]["blockers"]


def test_mismatched_spending_cap_rejects_only_that_variant(selections):
    scenarios, plans, budget = selections
    scenarios["feedback"] = scenarios["feedback"].model_copy(
        update={
            "constraints": scenarios["feedback"].constraints.model_copy(
                update={"budget_gbp": budget + 1}
            )
        }
    )
    result = paired.validate_variants(scenarios, plans, budget)
    assert result["baseline"]["structural_valid"]
    assert not result["feedback"]["structural_valid"]
    assert "spending limit differs" in result["feedback"]["blockers"][0]


def test_historical_receipts_cannot_be_fresh_results(selections, tmp_path, monkeypatch):
    monkeypatch.setattr(paired, "validate_pair", lambda _: {})
    with pytest.raises(ValueError, match="historical receipts rejected"):
        paired.compare_pair(
            tmp_path, tmp_path / "comparison", {"baseline": tmp_path / "historical"}
        )


def test_one_service_selection_compiles_using_existing_p08_and_executor(packages):  # noqa: F811
    inputs = tuple(
        adapt_planning_facts(p.admitted, p.policy.model_copy(update={"delivery_batch_limit": 30}))
        for p in packages
    )
    network = generate_freight_network(inputs, max_vehicles=1)
    plan = optimize_candidate_network(network.scenario).plan
    assert len(plan.routes) == 1
    compiled = compile_freight_network(network, plan)
    assert len(compiled) == 1
    assert compiled[0][0] == plan.routes[0].route_id
    with pytest.raises(ValueError, match="unproven"):
        compiled[0][1].selection_request()


@pytest.mark.parametrize("tamper", [None, "fresh_results", "status", "historical_reference"])
def test_cli_prepare_validate_compare_preserves_unknown_fresh_outcomes(
    controlled_source,  # noqa: F811
    selections,
    tmp_path,
    monkeypatch,
    capsys,  # noqa: F811
    tamper,
):
    scenarios, plans, budget = selections
    source = controlled_source
    (source / "planning-scenario.json").write_text(scenarios["baseline"].model_dump_json())
    (source / "execution-plan.json").write_text(plans["baseline"].model_dump_json())
    history = tmp_path / "CONTROLLED-history.sqlite"
    history.write_bytes(b"CONTROLLED evaluator boundary")
    comparison = {
        "evidence": {
            "evidence_directory": str(source),
            "history_path": str(history),
            "history_key": "CONTROLLED-key",
        },
        "scenarios": [
            {
                "name": "baseline" if name == "baseline" else "observed-error",
                "feasible": True,
                "scenario": scenarios[name].model_dump(mode="json"),
                "plan": plans[name].model_dump(mode="json"),
            }
            for name in plans
        ],
    }
    monkeypatch.setattr(paired, "compare_feedback_scenarios", lambda *a: comparison)
    historical = SimpleNamespace(
        metrics=[SimpleNamespace(name="total_capex", actual=Decimal("4101"))],
        model_dump=lambda **kw: {"status": "CONTROLLED-historical-reference"},
    )
    monkeypatch.setattr(paired, "load_verified_feedback", lambda *a: historical)
    monkeypatch.setattr(
        paired, "_compile_selections", lambda *a: {"CONTROLLED": "no-runtime-authority"}
    )
    pair, report = tmp_path / "pair", tmp_path / "report"
    assert (
        paired.main(
            [
                "prepare",
                str(source),
                "--feedback-history",
                str(history),
                "--feedback-run",
                "CONTROLLED-key",
                "--output",
                str(pair),
                "--budget",
                str(budget),
            ]
        )
        == 1
    )
    assert paired.main(["validate", str(pair)]) == 1
    assert paired.main(["compare", str(pair), "--output", str(report)]) == 1
    manifest = json.loads((pair / "paired-manifest.json").read_text())
    compared = json.loads((report / "comparison.json").read_text())
    assert manifest["fresh_results"] is None
    assert manifest["native_launches"] == manifest["admin_connections"] == 0
    assert compared["historical_reference"] == {"status": "CONTROLLED-historical-reference"}
    for variant in compared["variants"].values():
        assert variant["status"] == "not-executed"
        assert variant["evidence"] is None
        assert all(metric["actual"] is None for metric in variant["metrics"])
    assert "BLOCKED:" in capsys.readouterr().out
    if tamper is not None:
        manifest[tamper] = (
            {"forged": "CONTROLLED"} if tamper != "status" else "MATCHED NATIVE A/B READY"
        )
        (pair / "paired-manifest.json").write_text(json.dumps(manifest))
        with pytest.raises(ValueError):
            paired.validate_pair(pair)
