"""Deterministic experiment generation and descriptive comparison."""

from pathlib import Path
from statistics import mean, median, stdev

from pydantic import BaseModel, ConfigDict

from app.experiments.domain import ExperimentConfig, ExperimentResult, RunStatus, ScenarioConfig
from app.experiments.service import ExperimentService
from app.experiments.strategies import PlanningStrategy


class MetricSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    count: int
    mean: float
    median: float
    minimum: float
    maximum: float
    standard_deviation: float


class ComparisonReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenario: ScenarioConfig
    seeds: tuple[int, ...]
    duration_days: int
    openttd_version: str
    opengfx_version: str
    runs: tuple[ExperimentResult, ...]
    summaries: dict[str, dict[str, MetricSummary]]


def parse_seed_range(value: str) -> tuple[int, ...]:
    try:
        start_text, stop_text = value.split(":")
        start, stop = int(start_text), int(stop_text)
    except (ValueError, TypeError) as exc:
        raise ValueError("seeds must be a start:stop range, e.g. 0:10") from exc
    if start < 0 or stop <= start or stop > 2**32:
        raise ValueError("seed range must be nonempty and within unsigned 32-bit values")
    return tuple(range(start, stop))


def generate_comparison_configs(
    scenario: ScenarioConfig,
    strategies: tuple[PlanningStrategy, ...],
    seeds: tuple[int, ...],
    duration_days: int,
    *,
    openttd_version: str = "13.4",
    opengfx_version: str = "7.1",
) -> tuple[ExperimentConfig, ...]:
    if not strategies or not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("comparison requires strategies and distinct fixed seeds")
    if len({strategy.identifier for strategy in strategies}) != len(strategies):
        raise ValueError("comparison strategies must be distinct")
    return tuple(
        ExperimentConfig(
            scenario=scenario,
            planning=planning,
            ai=ai,
            openttd_version=openttd_version,
            opengfx_version=opengfx_version,
            seed=seed,
            duration_days=duration_days,
        )
        for seed in seeds
        for strategy in strategies
        for planning, ai in (strategy.configure(scenario),)
    )


def summarize_runs(runs: tuple[ExperimentResult, ...]) -> dict[str, dict[str, MetricSummary]]:
    values: dict[str, dict[str, list[float]]] = {}
    for run in runs:
        if run.status != RunStatus.SUCCEEDED or run.simulation is None:
            continue
        strategy_values = values.setdefault(run.config.planning.strategy_identifier, {})
        for metric in run.simulation.metrics:
            strategy_values.setdefault(metric.name, []).append(metric.value)
    return {
        strategy: {
            metric: MetricSummary(
                count=len(numbers),
                mean=mean(numbers),
                median=median(numbers),
                minimum=min(numbers),
                maximum=max(numbers),
                standard_deviation=stdev(numbers) if len(numbers) > 1 else 0.0,
            )
            for metric, numbers in metrics.items()
        }
        for strategy, metrics in values.items()
    }


def run_comparison(
    configs: tuple[ExperimentConfig, ...],
    service: ExperimentService,
    *,
    artifact_dir: Path,
) -> ComparisonReport:
    if not configs:
        raise ValueError("comparison requires at least one run")
    first = configs[0]
    common = (
        first.scenario,
        first.duration_days,
        first.openttd_version,
        first.opengfx_version,
    )
    strategy_seeds: dict[str, set[int]] = {}
    for config in configs:
        if (
            config.scenario,
            config.duration_days,
            config.openttd_version,
            config.opengfx_version,
        ) != common:
            raise ValueError(
                "comparison runs must share scenario, duration, and simulator versions"
            )
        seeds = strategy_seeds.setdefault(config.planning.strategy_identifier, set())
        if config.seed in seeds:
            raise ValueError("comparison has a repeated strategy and seed")
        seeds.add(config.seed)
    if len(strategy_seeds) < 2 or len({frozenset(seeds) for seeds in strategy_seeds.values()}) != 1:
        raise ValueError("comparison strategies must use exactly the same seed set")

    runs = tuple(service.run(config, artifact_dir=artifact_dir) for config in configs)
    return ComparisonReport(
        scenario=first.scenario,
        seeds=tuple(dict.fromkeys(config.seed for config in configs)),
        duration_days=first.duration_days,
        openttd_version=first.openttd_version,
        opengfx_version=first.opengfx_version,
        runs=runs,
        summaries=summarize_runs(runs),
    )
