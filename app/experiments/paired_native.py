"""Offline preparation and admission of matched native feedback experiments."""

import argparse
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from app.experiments.feedback_comparison import write_comparison
from app.experiments.feedback_experiment import semantic_plan
from app.experiments.freight_network import evaluate_freight_network
from app.planning.canonical import canonical_bytes, plan_hash, scenario_hash
from app.planning.domain import ExecutionPlan, PlanningScenario
from app.planning.feedback import compare_feedback_scenarios, load_verified_feedback
from app.planning.validation import validate_execution_plan
from app.simulation.openttd.freight_native_network import verify_network_receipt
from app.simulation.openttd.freight_planning import compile_freight_network

DEFAULT_BUDGET = Decimal("18000")


def validate_variants(scenarios, plans, budget, historical_capex=None):
    """Check each selection independently; historical costs never become fresh quotes."""
    if not budget.is_finite() or budget <= 0 or budget != budget.to_integral_value():
        raise ValueError("native budget must be positive integer GBP")
    variants = {}
    for name in ("baseline", "feedback"):
        scenario, plan = scenarios[name], plans[name]
        blockers = []
        structural_valid = False
        spending = None
        try:
            if scenario.constraints.budget_gbp != budget:
                raise ValueError("variant spending limit differs from paired budget")
            validate_execution_plan(plan, scenario)
            network = evaluate_freight_network(plan, scenario)
            spending = next(m.planned for m in network.metrics if m.name == "total_capex")
            if spending is None or spending > budget:
                raise ValueError("selected estimated CAPEX exceeds spending limit")
            structural_valid = True
        except ValueError as error:
            blockers.append(str(error))
        if name == "baseline" and historical_capex is not None and historical_capex > budget:
            blockers.append(
                f"historical selected baseline CAPEX GBP {historical_capex} exceeds "
                f"hard cap GBP {budget} by GBP {historical_capex - budget}; "
                "fresh execution must not relax this cap"
            )
        blockers.extend(
            (
                "fresh same-save native construction test quotes and company funds unavailable",
                "fresh native feasibility admission for ownership, cargo, "
                "engine and tile prerequisites unavailable",
                "existing native network executor accepts fresh heightmap preparation, "
                "not paired save clones",
            )
        )
        variants[name] = dict(
            structural_valid=structural_valid,
            checks="existing P05 finance, infrastructure, supply, fleet and capacity validator",
            estimated_capex_gbp=str(spending) if spending is not None else None,
            services=len(plan.routes),
            plan_digest=plan_hash(plan),
            scenario_digest=scenario_hash(scenario),
            native_ready=False,
            blockers=blockers,
        )
    return variants


def _semantic_identity(plan):
    return semantic_plan(ExecutionPlan.model_validate_json(canonical_bytes(plan)))


def _selected(source, history, key, budget):
    original = PlanningScenario.model_validate_json(
        (source / "planning-scenario.json").read_bytes()
    )
    scenario = original.model_copy(
        update={"constraints": original.constraints.model_copy(update={"budget_gbp": budget})}
    )
    comparison = compare_feedback_scenarios(scenario, history, key)
    rows = {r["name"]: r for r in comparison["scenarios"]}
    selected = {"baseline": rows["baseline"], "feedback": rows["observed-error"]}
    if any(not row["feasible"] for row in selected.values()):
        raise ValueError("a selected paired policy is optimizer-infeasible")
    scenarios = {
        name: PlanningScenario.model_validate_json(json.dumps(row["scenario"]))
        for name, row in selected.items()
    }
    plans = {
        name: ExecutionPlan.model_validate_json(json.dumps(row["plan"]))
        for name, row in selected.items()
    }
    return comparison, scenarios, plans


def _status(validation):
    reasons = [b for v in validation.values() for b in v["blockers"]]
    return "BLOCKED: " + reasons[0] if reasons else "MATCHED NATIVE A/B READY"


def _compile_selections(source, scenarios, plans):
    _, network = verify_network_receipt(source, return_network=True)
    return {
        name: [
            dict(
                route_id=route,
                source=service.source,
                destination=service.destination,
                cargo=service.cargo,
                engine=service.engine,
                capacity=service.capacity,
            )
            for route, service in compile_freight_network(
                replace(network, scenario=scenarios[name]), plans[name]
            )
        ]
        for name in plans
    }


def prepare_pair(source, history, key, output, *, budget=DEFAULT_BUDGET):
    from app.experiments.paired_source import prepare_paired_source

    raw = tuple(Path(p).absolute() for p in (source, history, output))
    if any(p.is_symlink() for path in raw for p in (path, *path.parents)):
        raise ValueError("paired paths must not contain symlinks")
    source, history, output = map(lambda p: p.resolve(), raw)
    if output.exists() or output.is_relative_to(source) or output == history:
        raise ValueError("paired output must be fresh and outside historical evidence")
    if not budget.is_finite() or budget <= 0 or budget != budget.to_integral_value():
        raise ValueError("native budget must be positive integer GBP")
    comparison, scenarios, plans = _selected(source, history, key, budget)
    feedback_source = Path(comparison["evidence"]["evidence_directory"]).resolve()
    if (
        output.is_relative_to(feedback_source)
        or source.is_relative_to(output)
        or feedback_source.is_relative_to(output)
        or history.is_relative_to(output)
    ):
        raise ValueError("paired output must be outside retained evidence and history")
    historical = load_verified_feedback(history, key)
    actual = next(m.actual for m in historical.metrics if m.name == "total_capex")
    historical_plan = ExecutionPlan.model_validate_json(
        (feedback_source / "execution-plan.json").read_bytes()
    )
    applicable_actual = (
        actual
        if _semantic_identity(plans["baseline"]) == _semantic_identity(historical_plan)
        else None
    )
    compiled = _compile_selections(source, scenarios, plans)
    validation = validate_variants(scenarios, plans, budget, applicable_actual)
    output.mkdir(parents=True)
    cloning = prepare_paired_source(source, output / "source")
    for name in plans:
        (output / f"{name}-scenario.json").write_bytes(canonical_bytes(scenarios[name]) + b"\n")
        (output / f"{name}-plan.json").write_bytes(canonical_bytes(plans[name]) + b"\n")
    manifest = dict(
        schema_version=1,
        classification="MATCHED_NATIVE_AB_PREPARATION",
        status=_status(validation),
        native_launches=0,
        admin_connections=0,
        budget_gbp=str(budget),
        budget_policy=(
            "integer GBP, unchanged hard cap; cost uncertainty is not zero "
            "or permission to overspend"
        ),
        source_directory=str(source),
        cloning=cloning,
        compiled_services=compiled,
        validation=validation,
        feedback_evidence=comparison["evidence"],
        historical_reference=historical.model_dump(mode="json"),
        historical_selected_baseline_capex_gbp=str(applicable_actual)
        if applicable_actual is not None
        else None,
        protected_directories=[str(source), str(feedback_source)],
        fresh_results=None,
    )
    (output / "paired-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def validate_pair(output):
    from app.experiments.paired_source import verify_paired_source

    output = Path(output).absolute()
    if any(p.is_symlink() for p in (output, *output.parents)) or any(
        (output / name).is_symlink()
        for name in (
            "paired-manifest.json",
            "baseline-plan.json",
            "feedback-plan.json",
            "baseline-scenario.json",
            "feedback-scenario.json",
        )
    ):
        raise ValueError("paired inputs must not contain symlinks")
    manifest = json.loads((output / "paired-manifest.json").read_bytes())
    cloning = verify_paired_source(output / "source")
    if (
        cloning != manifest["cloning"]
        or manifest["source_directory"] != cloning["source_directory"]
    ):
        raise ValueError("cloned source provenance changed")
    scenarios, plans = _inputs(output)
    evidence = manifest["feedback_evidence"]
    comparison, replay_scenarios, replay_plans = _selected(
        Path(manifest["source_directory"]),
        Path(evidence["history_path"]),
        evidence["history_key"],
        Decimal(manifest["budget_gbp"]),
    )
    if comparison["evidence"] != evidence or any(
        scenario_hash(scenarios[n]) != scenario_hash(replay_scenarios[n])
        or plan_hash(plans[n]) != plan_hash(replay_plans[n])
        for n in plans
    ):
        raise ValueError(
            "paired inputs differ from independent protected-source optimization replay"
        )
    if (
        _compile_selections(Path(manifest["source_directory"]), scenarios, plans)
        != manifest["compiled_services"]
    ):
        raise ValueError("compiled executor bindings changed")
    historical = load_verified_feedback(Path(evidence["history_path"]), evidence["history_key"])
    if (
        manifest["historical_reference"] != historical.model_dump(mode="json")
        or manifest["protected_directories"]
        != [manifest["source_directory"], evidence["evidence_directory"]]
        or manifest["fresh_results"] is not None
        or manifest["native_launches"] != 0
        or manifest["admin_connections"] != 0
        or manifest["classification"] != "MATCHED_NATIVE_AB_PREPARATION"
    ):
        raise ValueError("paired manifest outcome or historical provenance changed")
    historical_plan = ExecutionPlan.model_validate_json(
        (Path(evidence["evidence_directory"]) / "execution-plan.json").read_bytes()
    )
    actual = (
        next(m.actual for m in historical.metrics if m.name == "total_capex")
        if _semantic_identity(plans["baseline"]) == _semantic_identity(historical_plan)
        else None
    )
    if (str(actual) if actual is not None else None) != manifest[
        "historical_selected_baseline_capex_gbp"
    ]:
        raise ValueError("historical cost provenance changed")
    validation = validate_variants(scenarios, plans, Decimal(manifest["budget_gbp"]), actual)
    if validation != manifest["validation"] or _status(validation) != manifest["status"]:
        raise ValueError("paired selection or validation changed since preparation")
    return manifest


def _inputs(output):
    return (
        {
            n: PlanningScenario.model_validate_json((output / f"{n}-scenario.json").read_bytes())
            for n in ("baseline", "feedback")
        },
        {
            n: ExecutionPlan.model_validate_json((output / f"{n}-plan.json").read_bytes())
            for n in ("baseline", "feedback")
        },
    )


def compare_pair(output, report_output, native_directories=None):
    manifest = validate_pair(output)
    if native_directories:
        raise ValueError(
            "fresh paired native outcomes require supported executor and verified admission; "
            "historical receipts rejected"
        )
    scenarios, plans = _inputs(Path(output))
    report_output = Path(report_output)
    if report_output.exists() or report_output.resolve().is_relative_to(Path(output).resolve()):
        raise ValueError("comparison output must be fresh and outside paired inputs")
    return write_comparison(
        report_output,
        manifest,
        plans["baseline"],
        scenarios["baseline"],
        plans["feedback"],
        scenarios["feedback"],
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("source", type=Path)
    prepare.add_argument("--feedback-history", type=Path, required=True)
    prepare.add_argument("--feedback-run", required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--budget", type=Decimal, default=DEFAULT_BUDGET)
    validate = sub.add_parser("validate")
    validate.add_argument("pair", type=Path)
    compare = sub.add_parser("compare")
    compare.add_argument("pair", type=Path)
    compare.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare_pair(
                args.source,
                args.feedback_history,
                args.feedback_run,
                args.output,
                budget=args.budget,
            )
        elif args.command == "validate":
            result = validate_pair(args.pair)
        else:
            result = compare_pair(args.pair, args.output)["provenance"]
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(result["status"])
    return 1 if result["status"].startswith("BLOCKED:") else 0


if __name__ == "__main__":
    raise SystemExit(main())
