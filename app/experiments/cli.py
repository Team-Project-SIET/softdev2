"""One-command fixed-seed experiment spike."""

import argparse
from pathlib import Path

from app.experiments.comparison import (
    generate_comparison_configs,
    parse_seed_range,
    run_comparison,
)
from app.experiments.domain import ExperimentConfig, ScenarioConfig
from app.experiments.service import ExperimentService
from app.experiments.strategies import COMPARISON_STRATEGIES, BaselineStrategy


def generated_scenario(identifier: str = "generated-256-square") -> ScenarioConfig:
    if identifier != "generated-256-square":
        raise ValueError(f"unknown scenario: {identifier}")
    return ScenarioConfig(
        identifier=identifier,
        version="1",
        openttd_config="[game_creation]\nmap_x = 8\nmap_y = 8\n",
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="transport-experiment")
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="run the pinned trAIns baseline")
    run_parser.add_argument("--seed", type=int, default=17)
    run_parser.add_argument("--days", type=int, default=730)
    run_parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts/experiments"))
    compare_parser = commands.add_parser("compare", help="compare pinned SimpleAI mode policies")
    compare_parser.add_argument("--scenario", default="generated-256-square")
    compare_parser.add_argument("--strategies", required=True)
    compare_parser.add_argument("--seeds", required=True)
    compare_parser.add_argument("--days", type=int, default=730)
    compare_parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts/experiments"))
    args = parser.parse_args()

    try:
        scenario = generated_scenario(getattr(args, "scenario", "generated-256-square"))
    except ValueError as exc:
        parser.error(str(exc))
    if args.command == "compare":
        names = tuple(name.strip() for name in args.strategies.split(","))
        if len(names) < 2 or len(set(names)) != len(names):
            parser.error("compare requires at least two distinct strategies")
        unknown = set(names) - set(COMPARISON_STRATEGIES)
        if unknown:
            parser.error(f"unknown strategies: {', '.join(sorted(unknown))}")
        try:
            seeds = parse_seed_range(args.seeds)
            configs = generate_comparison_configs(
                scenario,
                tuple(COMPARISON_STRATEGIES[name] for name in names),
                seeds,
                args.days,
            )
        except ValueError as exc:
            parser.error(str(exc))
        report = run_comparison(configs, ExperimentService(), artifact_dir=args.artifact_dir)
        for run in report.runs:
            metrics = (
                " ".join(f"{metric.name}={metric.value:g}" for metric in run.simulation.metrics)
                if run.simulation is not None
                else f"error={run.error}"
            )
            print(
                f"run={run.run_id} strategy={run.config.planning.strategy_identifier} "
                f"seed={run.config.seed} status={run.status} {metrics}"
            )
        for strategy, summaries in report.summaries.items():
            for metric, summary in summaries.items():
                print(
                    f"summary strategy={strategy} metric={metric} count={summary.count} "
                    f"mean={summary.mean:g} median={summary.median:g} "
                    f"min={summary.minimum:g} max={summary.maximum:g} "
                    f"stddev={summary.standard_deviation:g}"
                )
        args.artifact_dir.mkdir(parents=True, exist_ok=True)
        report_path = args.artifact_dir / (
            f"comparison-{report.runs[0].run_id}-{report.runs[-1].run_id}.json"
        )
        report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        print(f"report={report_path.resolve()}")
        if any(run.status == "failed" for run in report.runs):
            raise SystemExit("comparison completed with failed runs")
        return

    planning, ai = BaselineStrategy().configure(scenario)
    config = ExperimentConfig(
        scenario=scenario,
        planning=planning,
        ai=ai,
        openttd_version="13.4",
        opengfx_version="7.1",
        seed=args.seed,
        duration_days=args.days,
    )
    result = ExperimentService().run(config, artifact_dir=args.artifact_dir)
    print(f"run={result.run_id} status={result.status}")
    if result.simulation is not None:
        print(f"simulation_date={result.simulation.simulation_date}")
        for metric in result.simulation.metrics:
            print(f"{metric.name}={metric.value} {metric.unit}")
        print(f"raw_artifact={result.simulation.raw_artifact_reference}")
    if result.error:
        raise SystemExit(result.error)
