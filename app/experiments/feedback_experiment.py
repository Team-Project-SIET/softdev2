"""Reproducible matched P05 decision experiment on verified retained inputs."""

import argparse
import hashlib
import json
from pathlib import Path

from app.experiments.freight_evaluation import evaluate_freight
from app.planning.canonical import canonical_bytes, plan_hash, scenario_hash
from app.planning.domain import ExecutionPlan, PlanningScenario
from app.planning.feedback import compare_feedback_scenarios


def semantic_plan(plan: ExecutionPlan) -> dict:
    """Execution decisions, excluding identifiers and changed cost estimates."""
    value = plan.model_dump(mode="json")
    actions = value["infrastructure"]["actions"]
    for action in actions:
        action.pop("estimated_build_cost_gbp")
    return dict(
        world_fingerprint=value["world_fingerprint"],
        routes=value["routes"],
        fleet=value["fleet"],
        infrastructure=value["infrastructure"],
        validation=value["validation"],
    )


def prepare_experiment(
    source: Path, history: Path, key: str, output: Path, *, sensitivity: bool = False
) -> dict:
    source, history, output = source.resolve(), history.resolve(), output.resolve()
    if output.exists() or output.is_relative_to(source) or output == history:
        raise ValueError("output must be a fresh directory outside retained evidence")
    files = (
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
    )
    hashes = {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in files}
    retained = evaluate_freight(source)
    if retained.status != "verified-delivery" or retained.network_report is None:
        raise ValueError("source requires independently verified native network receipts")
    scenario = PlanningScenario.model_validate_json(
        (source / "planning-scenario.json").read_bytes()
    )
    original = ExecutionPlan.model_validate_json((source / "execution-plan.json").read_bytes())
    comparison = compare_feedback_scenarios(scenario, history, key)
    feedback_source = Path(comparison["evidence"]["evidence_directory"]).resolve()
    if output.is_relative_to(feedback_source):
        raise ValueError("output must not modify retained feedback evidence")
    rows = {r["name"]: r for r in comparison["scenarios"]}
    baseline, feedback = rows["baseline"], rows["observed-error"]
    if not baseline["feasible"] or not feedback["feasible"]:
        raise ValueError("both matched policy scenarios must be optimizer-feasible")
    plans = {
        name: ExecutionPlan.model_validate_json(json.dumps(row["plan"]))
        for name, row in (("baseline", baseline), ("feedback", feedback))
    }
    if plan_hash(plans["baseline"]) != plan_hash(original):
        raise ValueError("baseline replay differs from verified retained source plan")
    links = json.loads((source / "prepared-source-links.json").read_bytes())
    before_digest = hashlib.sha256((source / "before.sav").read_bytes()).hexdigest()
    if before_digest != links["original_save_digest"]:
        raise ValueError("verified initial source save digest mismatch")
    differing = semantic_plan(plans["baseline"]) != semantic_plan(plans["feedback"])
    manifest: dict = dict(
        schema_version=1,
        experiment_source_files={
            str(path.relative_to(Path(__file__).resolve().parents[2])): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in (
                Path(__file__).resolve(),
                Path(__file__).with_name("feedback_comparison.py").resolve(),
                Path(__file__).resolve().parents[1] / "planning" / "feedback.py",
                Path(__file__).resolve().parents[1] / "planning" / "optimizer.py",
                Path(__file__).resolve().parents[1] / "planning" / "p08_network.py",
            )
        },
        classification="MATCHED_FEEDBACK_DECISION_EXPERIMENT",
        status="BLOCKED: existing native network policy forbids cloned retained save"
        if differing
        else "MATCHED FEEDBACK EXPERIMENT COMPLETE",
        plans_differ=differing,
        native_launches=0,
        native_launch_decision="blocked-clone-policy" if differing else "skipped-identical-plans",
        matched_inputs=dict(
            source_directory=str(source),
            source_file="before.sav",
            source_sha256=before_digest,
            observed_seed=json.loads((source / "runtime-identity.json").read_bytes())["welcome"][
                "seed"
            ],
            company_budget_policy=(
                "Both variants retain identical source company state; "
                "planning budget is a cap, not observed company balance."
            ),
            verified_source_files=hashes,
            prepared_source_links=links,
            runtime_identity=json.loads((source / "runtime-identity.json").read_bytes()),
            content_identity=json.loads((source / "graphics-identity.json").read_bytes()),
            policy=json.loads((source / "planning-policy.json").read_bytes()),
            world_fingerprint=scenario.world_fingerprint,
            scenario_digest=scenario_hash(scenario),
            constraints=scenario.constraints.model_dump(mode="json"),
            observation_policy="same retained qualified observation and supplied P08 candidates",
        ),
        assumptions=dict(
            infrastructure_cost_multiplier=feedback["infrastructure_cost_multiplier"],
            observed_error_gbp=comparison["observed_infrastructure_error_gbp"],
            observed_planned_gbp=comparison["observed_planned_infrastructure_gbp"],
            observed_actual_gbp=comparison["observed_actual_infrastructure_gbp"],
            interpretation=(
                "Uniform aggregate observed-error uplift; retrospective sensitivity, "
                "not calibrated prediction."
            ),
        ),
        feedback_evidence=comparison["evidence"],
        protected_directories=[str(source), str(feedback_source)],
        historical_reference=retained.model_dump(mode="json"),
        baseline=baseline,
        feedback=feedback,
        limitations=comparison["limitations"]
        + [
            "No fresh paired actual-performance outcomes are measured.",
            "Historical native receipts provide feedback provenance, "
            "not fresh matched variant outcomes.",
            "A different-plan experiment is blocked by the existing fresh-heightmap-only native "
            "policy; no launch is authorized by this command.",
        ],
    )
    if sensitivity:
        from app.experiments.feedback_sensitivity import analyze_sensitivity

        manifest["sensitivity"] = analyze_sensitivity(
            {
                row["name"]: PlanningScenario.model_validate_json(json.dumps(row["scenario"]))
                for row in comparison["scenarios"]
            }
        )
        manifest["experiment_source_files"]["app/experiments/feedback_sensitivity.py"] = (
            hashlib.sha256(
                Path(__file__).with_name("feedback_sensitivity.py").read_bytes()
            ).hexdigest()
        )

    from app.experiments.feedback_comparison import write_comparison

    if hashes != {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in files}:
        raise ValueError("source changed during experiment preparation")
    output.mkdir(parents=True, exist_ok=False)
    for name, row in (("baseline", baseline), ("feedback", feedback)):
        (output / f"{name}-scenario.json").write_bytes(
            canonical_bytes(PlanningScenario.model_validate_json(json.dumps(row["scenario"])))
            + b"\n"
        )
        (output / f"{name}-plan.json").write_bytes(canonical_bytes(plans[name]) + b"\n")
    (output / "planning-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    write_comparison(
        output,
        manifest,
        plans["baseline"],
        scenario,
        plans["feedback"],
        PlanningScenario.model_validate_json(json.dumps(feedback["scenario"])),
    )
    if hashes != {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in files}:
        raise ValueError("source changed during experiment reporting")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--feedback-history", type=Path, required=True)
    parser.add_argument("--feedback-run", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--sensitivity",
        action="store_true",
        help="exhaustive controlled budget sensitivity; zero native launches",
    )
    args = parser.parse_args(argv)
    try:
        manifest = prepare_experiment(
            args.source,
            args.feedback_history,
            args.feedback_run,
            args.output,
            sensitivity=args.sensitivity,
        )
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print("FEEDBACK DECISION SENSITIVITY COMPLETE" if args.sensitivity else manifest["status"])
    return 1 if manifest["plans_differ"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
