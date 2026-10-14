"""Explicit controlled cost sensitivity scenarios from replayed P07 history."""

import json
from decimal import ROUND_CEILING, Decimal, localcontext
from html import escape
from pathlib import Path

from app.experiments.freight_evaluation import document_digest, evaluate_freight
from app.experiments.freight_history import FreightHistory
from app.experiments.freight_network import NetworkEvaluation
from app.planning.canonical import plan_hash, scenario_hash
from app.planning.domain import PlanningScenario, RailComposition, RoadFleetOption
from app.planning.optimizer import OptimizerFailure, optimize_candidate_network


def load_verified_feedback(history_path: Path, history_key: str):
    if not history_path.is_file():
        raise ValueError("feedback history must already exist")
    history = FreightHistory(history_path)
    try:
        matches = [run for run in history.runs() if run.history_key == history_key]
    finally:
        history.close()
    if len(matches) != 1:
        raise ValueError("feedback run must identify one history entry")
    stored = matches[0]
    replay = evaluate_freight(Path(stored.source_directory))
    if document_digest(stored.model_dump(mode="json")) != document_digest(
        replay.model_dump(mode="json")
    ):
        raise ValueError("feedback evidence replay differs from stored history")
    if replay.status != "verified-delivery" or replay.network_report is None:
        raise ValueError("feedback requires verified native network evidence")
    return replay


def compare_feedback_scenarios(
    scenario: PlanningScenario, history_path: Path, history_key: str
) -> dict:
    run = load_verified_feedback(history_path, history_key)
    report = NetworkEvaluation.model_validate_json(json.dumps(run.network_report))
    comparison = compare_verified_feedback(scenario, report)
    comparison["evidence"] = dict(
        history_key=run.history_key,
        history_path=str(history_path.resolve()),
        evidence_directory=run.source_directory,
        receipt=run.receipt.model_dump(mode="json") if run.receipt else None,
        native_plan_digest=run.native_plan_digest,
        execution_plan_digest=run.execution_plan_digest,
        scenario_digest=report.scenario_digest,
        historical_world=run.cohort_definition.get("world"),
        comparison_world_fingerprint=scenario.world_fingerprint,
        references=[r.model_dump(mode="json") for r in report.evidence_refs],
    )
    return comparison


def compare_verified_feedback(scenario: PlanningScenario, report: NetworkEvaluation) -> dict:
    """Compare cost assumptions; caller must replay the retained evidence first."""
    if scenario.constraints.network_selection is None:
        raise ValueError("feedback comparison requires network selection constraints")
    if (
        report.classification != "NATIVE_MULTI_SERVICE_EVALUATION"
        or not report.native_execution_ready
    ):
        raise ValueError("feedback requires verified native network evidence")
    metric = next((m for m in report.metrics if m.name == "infrastructure_capex"), None)
    if metric is None or metric.planned is None or metric.planned <= 0 or metric.actual is None:
        raise ValueError("feedback requires measured and positive planned infrastructure CAPEX")
    with localcontext() as context:
        context.prec = 100
        error = max(Decimal(0), metric.actual - metric.planned)
        relative_error = error / metric.planned
        rows = []
        baseline_candidates = ()
        baseline_purchase = Decimal(0)
        for label, severity in (("baseline", 0), ("observed-error", 1), ("double-error", 2)):
            factor = Decimal(1) + relative_error * severity
            candidates = tuple(
                c.model_copy(
                    update={
                        "estimated_build_cost_gbp": (c.estimated_build_cost_gbp * factor).quantize(
                            Decimal("0.01"), rounding=ROUND_CEILING
                        )
                        if severity
                        else c.estimated_build_cost_gbp
                    }
                )
                for c in scenario.infrastructure_candidates
            )
            variant = scenario.model_copy(update={"infrastructure_candidates": candidates})
            row: dict = dict(
                name=label,
                infrastructure_cost_multiplier=str(factor),
                scenario_digest=scenario_hash(variant),
            )
            try:
                result = optimize_candidate_network(variant)
            except OptimizerFailure as exc:
                row.update(
                    feasible=False,
                    failure_code=exc.code.value,
                    reason=str(exc),
                    selected_services=[],
                    plan=None,
                    plan_digest=None,
                    expected_spending_gbp=None,
                    fleet_capacity_cargo_units=None,
                )
            else:
                plan = result.plan
                options = {o.option_id: o for o in variant.fleet_options}
                capacity = 0
                for group in plan.fleet.groups:
                    option = options[group.option_id]
                    if isinstance(option, RoadFleetOption):
                        per_vehicle = option.vehicle.capacity_cargo_units
                    else:
                        assert isinstance(group.composition, RailComposition)
                        per_vehicle = group.composition.total_capacity_cargo_units
                    capacity += group.count * per_vehicle
                infrastructure = result.metrics.infrastructure_spend_gbp
                purchase = result.metrics.vehicle_purchase_cost_gbp
                assert infrastructure is not None and purchase is not None
                spending = infrastructure + purchase
                row.update(
                    feasible=True,
                    failure_code=None,
                    selected_services=[
                        a.demand_id for r in plan.routes for a in r.cargo_assignments
                    ],
                    plan=plan.model_dump(mode="json"),
                    plan_digest=plan_hash(plan),
                    expected_spending_gbp=str(spending),
                    infrastructure_spending_gbp=str(result.metrics.infrastructure_spend_gbp),
                    vehicle_spending_gbp=str(result.metrics.vehicle_purchase_cost_gbp),
                    fleet_capacity_cargo_units=capacity,
                    planned_batch_cargo_units=result.metrics.predicted_delivered_cargo_units,
                    vehicles=sum(g.count for g in plan.fleet.groups),
                )
                if severity == 0:
                    baseline_candidates = tuple(a.candidate_id for a in plan.infrastructure.actions)
                    baseline_purchase = purchase
            costs = {c.candidate_id: c.estimated_build_cost_gbp for c in candidates}
            baseline_spend = sum((costs[c] for c in baseline_candidates), baseline_purchase)
            row["baseline_selection_spending_gbp"] = (
                str(baseline_spend) if baseline_candidates else None
            )
            row["baseline_selection_budget_feasible"] = (
                (
                    scenario.constraints.budget_gbp is None
                    or baseline_spend <= scenario.constraints.budget_gbp
                )
                if baseline_candidates
                else None
            )
            row["selected_candidate_ids"] = (
                [a.candidate_id for a in plan.infrastructure.actions] if row["feasible"] else []
            )
            row["scenario"] = variant.model_dump(mode="json")
            rows.append(row)
    return dict(
        schema_version=1,
        classification="CONTROLLED_OPTIMIZATION_FEEDBACK_COMPARISON",
        baseline_scenario_digest=scenario_hash(scenario),
        observed_infrastructure_error_gbp=str(error),
        observed_planned_infrastructure_gbp=str(metric.planned),
        observed_actual_infrastructure_gbp=str(metric.actual),
        scenarios=rows,
        limitations=[
            "Uniform aggregate observed-error and double-error uplifts are explicit stress "
            "assumptions, not statistically calibrated or candidate-specific predictions. "
            "Cross-world transfer is an explicit user-selected assumption. "
            "Costs round upward to pennies.",
            "Budget, supply, capacity, supplied P08 candidates, fleet and economic assumptions "
            "remain identical; only infrastructure cost assumptions vary.",
            "Waiting cargo is observed backlog; no demand, supply or guaranteed future "
            "revenue is inferred.",
            "OPEX, net return and profitability remain unknown. Retrospective sensitivity "
            "does not demonstrate optimization improvement or native feasibility.",
        ],
    )


def render_comparison_html(comparison: dict) -> str:
    rows = []
    for row in comparison["scenarios"]:
        cells = (
            row["name"],
            row["infrastructure_cost_multiplier"],
            ", ".join(row["selected_services"]) or "none",
            row.get("expected_spending_gbp") or "unknown",
            row.get("fleet_capacity_cargo_units") or "unknown",
            row["feasible"],
            row.get("reason", ""),
            row["baseline_selection_spending_gbp"],
            row["baseline_selection_budget_feasible"],
        )
        rows.append("<tr>" + "".join(f"<td>{escape(str(v))}</td>" for v in cells) + "</tr>")
    evidence = comparison.get("evidence", {})
    provenance = "".join(
        f"<li>{escape(key)}: <code>{escape(str(evidence.get(key)))}</code></li>"
        for key in ("history_key", "execution_plan_digest", "scenario_digest", "receipt")
    )
    return (
        "<section><h2>Controlled P05 feedback comparison</h2>"
        "<p>Observed infrastructure error: £"
        + escape(comparison["observed_infrastructure_error_gbp"])
        + ".</p>"
        + "<table><thead><tr><th>Scenario</th><th>Cost multiplier</th><th>Selected services</th>"
        "<th>Expected CAPEX GBP</th><th>Fleet capacity</th><th>Feasible</th><th>Failure</th>"
        "<th>Baseline CAPEX under assumption</th><th>Baseline within budget</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table><ul>"
        + "".join(f"<li>{escape(s)}</li>" for s in comparison["limitations"])
        + "</ul><h3>Replayed evidence provenance</h3><ul>"
        + provenance
        + "</ul></section>"
    )
