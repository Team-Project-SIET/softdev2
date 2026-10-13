"""Offline controlled multi-service planning and P07 report. No native execution."""

import argparse
from pathlib import Path

from app.experiments.freight_network import evaluate_freight_network
from app.planning.canonical import canonical_bytes
from app.planning.domain import ExecutionPlan, PlanningScenario
from app.planning.optimizer import optimize_candidate_network


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--native-network-directory",
        type=Path,
        help="Replay retained network receipt and its bound plan offline",
    )
    args = parser.parse_args(argv)
    scenario = PlanningScenario.model_validate_json(args.scenario.read_bytes())
    if scenario.constraints.network_selection is None:
        parser.error("scenario must declare shared network selection constraints")
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
        result = optimize_candidate_network(scenario)
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
    print(
        f"{report.classification}: {len(plan.routes)} services; "
        f"{report.verified_service_count} verified; offline report only"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
