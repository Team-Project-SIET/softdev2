"""Offline controlled multi-service planning and P07 report. No native execution."""

import argparse
import json
from pathlib import Path

from app.experiments.freight_network import evaluate_freight_network
from app.planning.canonical import canonical_bytes
from app.planning.domain import ExecutionPlan, PlanningScenario
from app.planning.optimizer import OptimizerFailure, optimize_candidate_network


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--native-network-directory",
        type=Path,
        help="Replay retained network receipt and its bound plan offline",
    )
    parser.add_argument("--feedback-history", type=Path)
    parser.add_argument(
        "--feedback-run", help="Receipt history key to replay for explicit cost stress scenarios"
    )
    args = parser.parse_args(argv)
    if bool(args.feedback_history) != bool(args.feedback_run):
        parser.error("--feedback-history and --feedback-run must appear together")
    if args.feedback_history and args.native_network_directory:
        parser.error("feedback comparison cannot be combined with native network replay")
    comparison = None
    history_runs = ()
    if args.feedback_history:
        from app.experiments.freight_history import FreightHistory
        from app.planning.feedback import compare_feedback_scenarios

        if not args.feedback_history.is_file():
            parser.error("feedback history must already exist")
        history = FreightHistory(args.feedback_history)
        try:
            history_runs = history.runs()
        finally:
            history.close()
        destinations = [
            args.output,
            *(
                args.output / name
                for name in (
                    "execution-plan.json",
                    "estimates.json",
                    "evaluation.json",
                    "planning-comparison.json",
                    "charts.html",
                )
            ),
        ]
        if any(
            target.resolve() == source.resolve()
            for target in destinations
            for source in (args.scenario, args.feedback_history)
        ) or any(
            target.resolve().is_relative_to(Path(run.source_directory).resolve())
            for target in destinations
            for run in history_runs
        ):
            parser.error("output must not modify scenario, history or retained evidence")
    scenario = PlanningScenario.model_validate_json(args.scenario.read_bytes())
    if scenario.constraints.network_selection is None:
        parser.error("scenario must declare shared network selection constraints")
    if args.feedback_history:
        try:
            comparison = compare_feedback_scenarios(
                scenario, args.feedback_history, args.feedback_run
            )
        except (OSError, ValueError) as error:
            parser.error(str(error))
    if args.native_network_directory:
        plan = ExecutionPlan.model_validate_json(
            (args.native_network_directory / "execution-plan.json").read_bytes()
        )
        report = evaluate_freight_network(
            plan, scenario, native_network_directory=args.native_network_directory
        )
        outputs = (("execution-plan.json", plan), ("evaluation.json", report))
        if args.output.resolve().is_relative_to(args.native_network_directory.resolve()):
            parser.error("output must not modify retained evidence")
    else:
        try:
            result = optimize_candidate_network(scenario)
        except OptimizerFailure:
            if comparison is None:
                raise
            if any(
                (args.output / name).exists()
                for name in ("execution-plan.json", "estimates.json", "evaluation.json")
            ):
                parser.error(
                    "infeasible baseline requires an output directory without baseline artifacts"
                )
            outputs = ()
        else:
            plan = result.plan
            report = evaluate_freight_network(plan, scenario)
            outputs = (
                ("execution-plan.json", plan),
                ("estimates.json", result.metrics),
                ("evaluation.json", report),
            )
    for name, _ in outputs:
        if (args.output / name).resolve() == args.scenario.resolve() or (
            args.native_network_directory
            and (args.output / name)
            .resolve()
            .is_relative_to(args.native_network_directory.resolve())
        ):
            parser.error("output must not modify scenario or retained evidence")
    args.output.mkdir(parents=True, exist_ok=True)
    for name, value in outputs:
        (args.output / name).write_bytes(canonical_bytes(value) + b"\n")
    if comparison is not None:
        from app.experiments.freight_analytics import render_html, summarize

        (args.output / "planning-comparison.json").write_text(
            json.dumps(comparison, indent=2) + "\n"
        )
        summary = summarize(history_runs)
        summary["planning_comparison"] = comparison
        (args.output / "charts.html").write_text(render_html(history_runs, summary))
    if comparison is not None:
        print(f"{comparison['classification']}: offline report only")
        for row in comparison["scenarios"]:
            print(
                f"{row['name']}: {len(row['selected_services'])} services; "
                f"CAPEX GBP {row['expected_spending_gbp']}; "
                f"capacity {row['fleet_capacity_cargo_units']}; feasible={row['feasible']}"
            )
    else:
        print(
            f"{report.classification}: {len(plan.routes)} services; "
            f"{report.verified_service_count} verified; offline report only"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
