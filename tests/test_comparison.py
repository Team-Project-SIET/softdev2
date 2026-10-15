import json
from collections import Counter
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.experiments.comparison import (
    generate_comparison_configs,
    parse_seed_range,
    run_comparison,
    summarize_runs,
)
from app.experiments.domain import (
    ExperimentConfig,
    Metric,
    RunStatus,
    ScenarioConfig,
    SimulationResult,
)
from app.experiments.model import ExperimentMetricRecord, ExperimentRunRecord
from app.experiments.service import ExperimentService
from app.experiments.strategies import SimpleMultimodalStrategy, SimpleRoadOnlyStrategy


def comparison_configs(seeds: tuple[int, ...] = (0, 1)) -> tuple[ExperimentConfig, ...]:
    return generate_comparison_configs(
        ScenarioConfig(identifier="generated-256-square", version="1"),
        (SimpleMultimodalStrategy(), SimpleRoadOnlyStrategy()),
        seeds,
        730,
    )


def test_strategy_configuration_is_stable_serializable_and_reaches_ai() -> None:
    configs = comparison_configs((0,))
    assert [config.planning.strategy_identifier for config in configs] == [
        "simple-multimodal",
        "simple-road-only",
    ]
    assert all(config.planning.strategy_version == "1" for config in configs)
    assert all(config.ai.md5 == "b3137bbd0c73641cf510ead06e36dab6" for config in configs)
    assert configs[0].planning.parameters == {
        "use_trains": "1",
        "use_roadvehs": "1",
        "use_aircraft": "1",
    }
    assert configs[1].planning.parameters == {
        "use_trains": "0",
        "use_roadvehs": "1",
        "use_aircraft": "0",
    }
    for config in configs:
        assert config.ai.parameters == tuple(sorted(config.planning.parameters.items()))
        assert ExperimentConfig.model_validate_json(config.model_dump_json()) == config
        assert json.loads(config.model_dump_json())["ai"]["parameters"]


def test_generation_pairs_same_seed_set_and_is_deterministic() -> None:
    configs = comparison_configs(parse_seed_range("0:10"))
    assert len(configs) == 20
    assert Counter(config.planning.strategy_identifier for config in configs) == {
        "simple-multimodal": 10,
        "simple-road-only": 10,
    }
    assert (
        {
            config.seed
            for config in configs
            if config.planning.strategy_identifier == "simple-multimodal"
        }
        == {
            config.seed
            for config in configs
            if config.planning.strategy_identifier == "simple-road-only"
        }
        == set(range(10))
    )
    assert [config.model_dump_json() for config in configs] == [
        config.model_dump_json() for config in comparison_configs(parse_seed_range("0:10"))
    ]
    assert {
        (config.openttd_version, config.opengfx_version, config.duration_days) for config in configs
    } == {("13.4", "7.1", 730)}


@pytest.mark.parametrize("value", ["", "0", "2:2", "4:2", "-1:2", "0:4294967297"])
def test_invalid_seed_ranges_are_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="seed|seeds"):
        parse_seed_range(value)


def test_comparison_rejects_mismatched_inputs_before_running(tmp_path: Path) -> None:
    configs = comparison_configs()

    class NeverRun:
        def run(self, config, *, artifact_dir):
            raise AssertionError("simulation must not start")

    mismatched = configs[:-1]
    with pytest.raises(ValueError, match="same seed set"):
        run_comparison(mismatched, NeverRun(), artifact_dir=tmp_path)
    changed = configs[-1].model_copy(update={"openttd_version": "15.0"})
    with pytest.raises(ValueError, match="share scenario"):
        run_comparison((*configs[:-1], changed), NeverRun(), artifact_dir=tmp_path)


class DeterministicRunner:
    def run(self, config: ExperimentConfig, *, run_id: int, artifact_dir: Path) -> SimulationResult:
        if config.seed == 1 and config.planning.strategy_identifier == "simple-road-only":
            raise RuntimeError("policy execution failed")
        multiplier = 2 if config.planning.strategy_identifier == "simple-multimodal" else 1
        return SimulationResult(
            simulation_date=date(1951, 12, 1),
            savegame_version=302,
            metrics=(
                Metric(name="company_money", value=(config.seed + 1) * multiplier, unit="GBP"),
                Metric(
                    name="current_period_cargo_delivered", value=10 * multiplier, unit="cargo_units"
                ),
            ),
            raw_artifact_reference=str(artifact_dir / f"experiment-{run_id}.json.gz"),
        )


def test_all_runs_persist_with_strategy_identity_and_one_failure_is_isolated(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    report = run_comparison(
        comparison_configs(),
        ExperimentService(session_factory, DeterministicRunner()),
        artifact_dir=tmp_path,
    )
    assert len(report.runs) == 4
    assert [run.status for run in report.runs] == [
        RunStatus.SUCCEEDED,
        RunStatus.SUCCEEDED,
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
    ]
    assert report.runs[-1].error == "policy execution failed"
    assert report.summaries["simple-multimodal"]["company_money"].count == 2
    assert report.summaries["simple-road-only"]["company_money"].count == 1

    with session_factory() as session:
        runs = session.scalars(select(ExperimentRunRecord).order_by(ExperimentRunRecord.id)).all()
        assert len(runs) == 4
        assert {(run.strategy.identifier, run.strategy.version) for run in runs} == {
            ("simple-multimodal", "1"),
            ("simple-road-only", "1"),
        }
        for run in runs:
            assert run.strategy_configuration == dict(run.ai_configuration["parameters"])
            assert run.ai_configuration["md5"] == "b3137bbd0c73641cf510ead06e36dab6"
            assert run.seed in (0, 1)
            assert run.duration_days == 730
        assert runs[-1].status == RunStatus.FAILED
        assert runs[-1].simulation is None
        assert session.scalar(select(func.count()).select_from(ExperimentMetricRecord)) == 6


def test_descriptive_statistics_use_individual_successful_runs(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    report = run_comparison(
        comparison_configs((0, 1, 2)),
        ExperimentService(session_factory, DeterministicRunner()),
        artifact_dir=tmp_path,
    )
    summary = report.summaries["simple-multimodal"]["company_money"]
    assert summary.count == 3
    assert (summary.mean, summary.median, summary.minimum, summary.maximum) == (4, 4, 2, 6)
    assert summary.standard_deviation == 2
    road_summary = report.summaries["simple-road-only"]["company_money"]
    assert road_summary.count == 2
    assert (road_summary.mean, road_summary.median, road_summary.minimum, road_summary.maximum) == (
        2,
        2,
        1,
        3,
    )
    assert road_summary.standard_deviation == pytest.approx(2**0.5)
    assert summarize_runs(report.runs) == report.summaries
    assert len(json.loads(report.model_dump_json())["runs"]) == 6
