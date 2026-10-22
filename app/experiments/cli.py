"""Argparse presentation for batch experiments and one explicit live run."""

import argparse
import signal
import sys
from pathlib import Path

from app.experiments.cancellation import LiveCancellation
from app.experiments.comparison import (
    generate_comparison_configs,
    parse_seed_range,
    run_comparison,
)
from app.experiments.domain import ExecutionMode, ExperimentConfig, ScenarioConfig
from app.experiments.outcome_recovery import OutcomeRecoveryService, RecoveryStatus
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="transport-experiment")
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="run the pinned trAIns baseline")
    run_parser.add_argument("--seed", type=int, default=17)
    run_parser.add_argument("--days", type=int, default=730)
    run_parser.add_argument(
        "--strategy", choices=("baseline", *COMPARISON_STRATEGIES), default="baseline"
    )
    run_parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts/experiments"))
    run_parser.add_argument(
        "--mode",
        choices=("batch", "live"),
        default="batch",
        help="live runs at normal speed; incomplete telemetry returns exit code 3",
    )
    recover_parser = commands.add_parser(
        "recover", help="reconcile a validated live outcome manifest without rerunning"
    )
    recover_parser.add_argument("manifest", type=Path)
    recover_parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts/experiments"))
    compare_parser = commands.add_parser("compare", help="compare pinned SimpleAI mode policies")
    compare_parser.add_argument("--scenario", default="generated-256-square")
    compare_parser.add_argument("--strategies", required=True)
    compare_parser.add_argument("--seeds", required=True)
    compare_parser.add_argument("--days", type=int, default=730)
    compare_parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts/experiments"))
    analytics_parser = commands.add_parser(
        "analyze-freight", help="evaluate retained native freight receipts offline"
    )
    analytics_parser.add_argument("attempts", type=Path, nargs="+")
    analytics_parser.add_argument(
        "--history", type=Path, default=Path("artifacts/experiments/freight-history.sqlite")
    )
    analytics_parser.add_argument(
        "--output", type=Path, default=Path("artifacts/experiments/p07-freight")
    )
    continuous_parser = commands.add_parser(
        "analyze-continuous-freight",
        help="replay continuous observations and export P07 charts offline",
    )
    continuous_parser.add_argument("attempt", type=Path)
    continuous_parser.add_argument("--output", type=Path, required=True)
    continuous_parser.add_argument("--recovery-directory", type=Path)
    continuous_parser.add_argument(
        "--compare-planning",
        action="store_true",
        help="also export opt-in controlled P08/P05 alternatives; no native predictions",
    )
    continuous_parser.add_argument(
        "--prepare-capacity-experiment",
        action="store_true",
        help="prepare explicit A/B/C vehicle allocations offline; never launches OpenTTD",
    )
    insights_parser = commands.add_parser(
        "analyze-performance-insights",
        help=(
            "agent-b-additive: derive offline performance insights, bottleneck "
            "hypotheses and advisory recommendations from retained P07 reports"
        ),
    )
    insights_parser.add_argument("SOURCE", type=Path)
    insights_parser.add_argument("--output", type=Path, required=True)
    insights_parser.add_argument(
        "--compare",
        type=Path,
        nargs="*",
        default=(),
        help="additional retained P07 report directories to compare",
    )
    args = parser.parse_args(argv)

    if args.command == "analyze-performance-insights":
        import json

        from app.experiments.performance_insights import analyze_performance

        try:
            result = analyze_performance(args.SOURCE, args.output, compare=args.compare)
        except (OSError, ValueError, KeyError, TypeError) as error:
            # Malformed retained documents also reject cleanly without output.
            print(f"analysis rejected: {error}", file=sys.stderr)
            return 1
        print(json.dumps(result, sort_keys=True))
        return 0

    if args.command == "analyze-continuous-freight":
        import json

        from app.experiments.freight_continuous_analytics import analyze_continuous

        try:
            extra_names = []
            if args.compare_planning:
                extra_names.append("planning-alternatives.json")
            if args.prepare_capacity_experiment:
                extra_names.extend(("capacity-experiment.json", "capacity-comparison.html"))
            protected = [args.attempt, args.recovery_directory]
            if any(
                (args.output / name).resolve().is_relative_to(root.resolve())
                for name in extra_names
                for root in protected
                if root is not None
            ):
                raise ValueError("planning comparison output must not modify retained evidence")
            result = analyze_continuous(
                args.attempt, args.output, recovery_directory=args.recovery_directory
            )
            if args.compare_planning:
                from app.experiments.freight_alternatives import compare_freight_alternatives
                from app.planning.domain import PlanningScenario

                scenario = PlanningScenario.model_validate_json(
                    (args.attempt / "planning-scenario.json").read_bytes()
                )
                comparison = compare_freight_alternatives(scenario)
                destination = args.output / "planning-alternatives.json"
                destination.write_text(json.dumps(comparison, indent=2) + "\n")
                result["planning_alternatives"] = str(destination)
            if args.prepare_capacity_experiment:
                from app.experiments.capacity_experiment import prepare_capacity_experiment
                from app.experiments.freight_capacity_report import render_capacity_report

                report = json.loads((args.output / "summary.json").read_bytes())
                comparison = prepare_capacity_experiment(args.attempt, report)
                destination = args.output / "capacity-experiment.json"
                destination.write_text(json.dumps(comparison, indent=2) + "\n")
                (args.output / "capacity-comparison.html").write_text(
                    render_capacity_report(comparison)
                )
                result["capacity_experiment"] = str(destination)
        except (OSError, ValueError) as error:
            print(f"analysis rejected: {error}", file=sys.stderr)
            return 1
        print(json.dumps(result, sort_keys=True))
        return 0

    if args.command == "analyze-freight":
        import json

        from app.experiments.freight_analytics import analyze

        try:
            result = analyze(args.attempts, args.history, args.output)
        except (OSError, ValueError) as error:
            print(f"analysis rejected: {error}", file=sys.stderr)
            return 1
        print(json.dumps(result, sort_keys=True))
        return 0

    if args.command == "recover":
        recovery = OutcomeRecoveryService().recover(args.artifact_dir, args.manifest)
        run_part = f" run={recovery.run_id}" if recovery.run_id is not None else ""
        cleanup_part = " workspace_cleanup=pending" if recovery.workspace_cleanup_pending else ""
        print(f"recovery={recovery.status}{run_part}{cleanup_part}")
        return (
            0
            if recovery.status
            in {
                RecoveryStatus.RECOVERED,
                RecoveryStatus.ALREADY_RECONCILED,
            }
            else 1
        )

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
            print("comparison completed with failed runs", file=sys.stderr)
            return 1
        return 0

    strategy = (
        BaselineStrategy() if args.strategy == "baseline" else COMPARISON_STRATEGIES[args.strategy]
    )
    planning, ai = strategy.configure(scenario)
    config = ExperimentConfig(
        scenario=scenario,
        planning=planning,
        ai=ai,
        openttd_version="13.4",
        opengfx_version="7.1",
        seed=args.seed,
        duration_days=args.days,
    )
    mode = ExecutionMode(args.mode)
    if mode is ExecutionMode.LIVE:
        live_cancellation = LiveCancellation()
        previous_int = signal.getsignal(signal.SIGINT)
        previous_term = signal.getsignal(signal.SIGTERM)

        def request_cancel(received: int, _frame: object) -> None:
            live_cancellation.request("SIGINT" if received == signal.SIGINT else "SIGTERM")

        try:
            signal.signal(signal.SIGINT, request_cancel)
            signal.signal(signal.SIGTERM, request_cancel)
            result = ExperimentService(live_cancellation=live_cancellation).run(
                config, artifact_dir=args.artifact_dir, execution_mode=mode
            )
        finally:
            signal.signal(signal.SIGINT, previous_int)
            signal.signal(signal.SIGTERM, previous_term)
        cancellation = live_cancellation
    else:
        cancellation = None
        result = ExperimentService().run(
            config, artifact_dir=args.artifact_dir, execution_mode=mode
        )
    if mode is ExecutionMode.LIVE:
        telemetry = result.live_summary.telemetry_status if result.live_summary else None
        suffix = f" telemetry={telemetry}" if telemetry is not None else ""
        print(f"run={result.run_id} mode=live status={result.status}{suffix}")
    else:
        print(f"run={result.run_id} status={result.status}")
    if result.simulation is not None:
        print(f"simulation_date={result.simulation.simulation_date}")
        if mode is ExecutionMode.LIVE and result.live_summary is not None:
            summary = result.live_summary
            for key, value in (
                ("requested_target_day", summary.requested_target_day),
                ("last_observed_day", summary.last_observed_day),
                ("actual_final_day", summary.actual_final_day),
            ):
                if value is not None:
                    print(f"{key}={value}")
        for metric in result.simulation.metrics:
            print(f"{metric.name}={metric.value} {metric.unit}")
        if mode is ExecutionMode.BATCH:
            print(f"raw_artifact={result.simulation.raw_artifact_reference}")
        elif result.live_summary is not None:
            if result.live_summary.raw_save_reference is not None:
                print(f"raw_save={result.live_summary.raw_save_reference}")
            if result.live_summary.parsed_artifact_reference is not None:
                print(f"parsed_artifact={result.live_summary.parsed_artifact_reference}")
    if mode is ExecutionMode.LIVE and result.status == "failed" and result.failure_code is not None:
        print(f"failure_code={result.failure_code}")
    if result.error:
        if mode is ExecutionMode.LIVE:
            print(f"error={result.error}")
        else:
            print(result.error, file=sys.stderr)
    if result.terminal_persistence_failed or (
        result.outcome_manifest_failed and result.status == "succeeded"
    ):
        return 1
    if result.status == "failed":
        if result.failure_code == "timeout":
            return 124
        if result.failure_code == "cancelled":
            if cancellation is not None and cancellation.signal_name == "SIGTERM":
                return 143
            return 130
        return 1
    if mode is ExecutionMode.LIVE and result.live_summary is not None:
        if result.live_summary.telemetry_status == "incomplete":
            return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
