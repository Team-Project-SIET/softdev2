"""Offline controlled multi-service planning and P07 report. No native execution."""

import argparse
from pathlib import Path

from app.experiments.freight_network import evaluate_freight_network
from app.planning.canonical import canonical_bytes
from app.planning.domain import PlanningScenario
from app.planning.optimizer import optimize_candidate_network


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    scenario = PlanningScenario.model_validate_json(args.scenario.read_bytes())
    if scenario.constraints.network_selection is None:
        parser.error("scenario must declare shared network selection constraints")
    result = optimize_candidate_network(scenario)
    report = evaluate_freight_network(result.plan, scenario)
    args.output.mkdir(parents=True, exist_ok=True)
    for name, value in (
        ("execution-plan.json", result.plan),
        ("estimates.json", result.metrics),
        ("evaluation.json", report),
    ):
        (args.output / name).write_bytes(canonical_bytes(value) + b"\n")
    print(
        f"CONTROLLED MULTI-SERVICE OPTIMIZATION COMPLETE: {len(result.plan.routes)} services; "
        "native execution unproven"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
