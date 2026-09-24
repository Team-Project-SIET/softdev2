"""One-command fixed-seed experiment spike."""

import argparse
from pathlib import Path

from app.experiments.domain import ExperimentConfig, ScenarioConfig
from app.experiments.service import ExperimentService
from app.experiments.strategies import BaselineStrategy


def main() -> None:
    parser = argparse.ArgumentParser(prog="transport-experiment")
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="run the pinned trAIns baseline")
    run_parser.add_argument("--seed", type=int, default=17)
    run_parser.add_argument("--days", type=int, default=730)
    run_parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts/experiments"))
    args = parser.parse_args()

    scenario = ScenarioConfig(
        identifier="generated-256-square",
        version="1",
        openttd_config="[game_creation]\nmap_x = 8\nmap_y = 8\n",
    )
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
