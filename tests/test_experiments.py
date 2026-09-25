import gzip
import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.experiments import domain
from app.experiments.domain import (
    ExperimentConfig,
    Metric,
    RunStatus,
    ScenarioConfig,
    SimulationResult,
)
from app.experiments.model import ExperimentMetricRecord, ExperimentRunRecord
from app.experiments.service import ExperimentService
from app.experiments.strategies import BaselineStrategy
from app.simulation.openttd.runner import OpenTTDLabRunner, parse_result_row


def baseline_config(*, seed: int = 17, days: int = 365) -> ExperimentConfig:
    scenario = ScenarioConfig(identifier="test-map", version="1", openttd_config="")
    planning, ai = BaselineStrategy().configure(scenario)
    return ExperimentConfig(
        scenario=scenario,
        planning=planning,
        ai=ai,
        openttd_version="13.4",
        opengfx_version="7.1",
        seed=seed,
        duration_days=days,
    )


def parsed_row(config: ExperimentConfig) -> dict:
    return {
        "date": date(1950, 12, 1),
        "error": False,
        "openttd_version": config.openttd_version,
        "opengfx_version": config.opengfx_version,
        "savegame_version": 213,
        "experiment": {"seed": config.seed, "days": config.duration_days},
        "chunks": {
            "PLYR": {
                "0": {
                    "money": 7858,
                    "current_loan": 290000,
                    "cur_economy": [
                        {
                            "income": 12,
                            "expenses": -1026,
                            "delivered_cargo": [3, 4],
                        }
                    ],
                }
            }
        },
    }


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"seed": -1}, "seed"),
        ({"duration_days": 0}, "duration_days"),
        ({"openttd_version": "latest"}, "pinned"),
        ({"opengfx_version": "latest"}, "pinned"),
    ],
)
def test_experiment_configuration_validation(changes: dict, error: str) -> None:
    with pytest.raises(ValidationError, match=error):
        ExperimentConfig.model_validate({**baseline_config().model_dump(), **changes})


def test_fixed_seed_and_pinned_ai_are_sent_to_openttdlab(tmp_path: Path) -> None:
    config = baseline_config(seed=314, days=90)
    captured = {}

    def fake_run_experiments(**kwargs):
        captured.update(kwargs)
        return [parsed_row(config)]

    result = OpenTTDLabRunner(fake_run_experiments).run(config, run_id=7, artifact_dir=tmp_path)

    assert captured["experiments"][0]["seed"] == 314
    assert captured["experiments"][0]["days"] == 90
    assert captured["openttd_version"] == "13.4"
    assert captured["opengfx_version"] == "7.1"
    assert captured["max_workers"] == 1
    assert captured["experiments"][0]["ais"][0][1] == config.ai.parameters
    assert {(metric.name, metric.value) for metric in result.metrics} >= {
        ("company_money", 7858),
        ("current_period_cargo_delivered", 7),
    }
    assert result.raw_artifact_reference is not None
    with gzip.open(result.raw_artifact_reference, "rt", encoding="utf-8") as artifact:
        assert json.load(artifact)["chunks"]["PLYR"]["0"]["money"] == 7858


def test_parser_rejects_wrong_seed_and_ai_errors() -> None:
    config = baseline_config()
    row = parsed_row(config)
    row["experiment"]["seed"] += 1
    with pytest.raises(ValueError, match="different experiment"):
        parse_result_row(row, config)
    row["experiment"]["seed"] = config.seed
    row["error"] = True
    with pytest.raises(RuntimeError, match="script failure"):
        parse_result_row(row, config)


class FakeRunner:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def run(self, config: ExperimentConfig, *, run_id: int, artifact_dir: Path) -> SimulationResult:
        if self.fail:
            raise RuntimeError("simulator exited")
        return SimulationResult(
            simulation_date=date(1950, 12, 1),
            savegame_version=213,
            metrics=(Metric(name="company_money", value=7858, unit="GBP"),),
            raw_artifact_reference=str(artifact_dir / f"experiment-{run_id}.json.gz"),
        )


def test_metadata_and_metrics_are_persisted(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    config = baseline_config()
    result = ExperimentService(session_factory, FakeRunner()).run(config, artifact_dir=tmp_path)
    assert result.status is RunStatus.SUCCEEDED
    assert result.execution_mode is domain.ExecutionMode.BATCH
    assert set(result.model_dump()) == {
        "run_id",
        "config",
        "status",
        "started_at",
        "completed_at",
        "simulation",
        "error",
    }
    assert set(json.loads(result.model_dump_json())["simulation"]) == {
        "simulation_date",
        "savegame_version",
        "metrics",
        "raw_artifact_reference",
    }
    assert "execution_mode" not in result.config.model_dump()

    with session_factory() as session:
        run = session.get(ExperimentRunRecord, result.run_id)
        assert run is not None and run.simulation is not None
        assert result.simulation is not None
        assert run.scenario.identifier == "test-map"
        assert run.strategy.identifier == "trains-baseline"
        assert run.ai_configuration["md5"] == config.ai.md5
        assert run.seed == 17
        assert run.duration_days == 365
        assert run.started_at is not None and run.completed_at is not None
        assert run.raw_artifact_reference == result.simulation.raw_artifact_reference
        assert run.simulation.savegame_version == 213
        metric = session.scalar(select(ExperimentMetricRecord))
        assert metric is not None
        assert metric.name == "company_money"
        assert metric.value == 7858


def test_failed_simulation_is_persisted_without_success_metrics(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    result = ExperimentService(session_factory, FakeRunner(fail=True)).run(
        baseline_config(), artifact_dir=tmp_path
    )
    assert result.status is RunStatus.FAILED
    assert result.error == "simulator exited"
    with session_factory() as session:
        run = session.get(ExperimentRunRecord, result.run_id)
        assert run is not None
        assert run.status == RunStatus.FAILED
        assert run.completed_at is not None
        assert run.simulation is None
        assert session.scalar(select(ExperimentMetricRecord)) is None


def test_default_service_keeps_batch_lab_metrics_and_artifact(
    session_factory: sessionmaker[Session], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket
    import subprocess
    import time

    import openttdlab

    config = baseline_config(seed=314, days=90)
    captured = {}

    def lab_boundary(**kwargs):
        captured.update(kwargs)
        return [parsed_row(config)]

    def forbidden(*args, **kwargs):
        pytest.fail("Batch adapter acquired unexpected live network/process/sleep work")

    monkeypatch.setattr(openttdlab, "run_experiments", lab_boundary)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(time, "sleep", forbidden)
    service = ExperimentService(session_factory)
    assert isinstance(service.runner, OpenTTDLabRunner)
    result = service.run(config, artifact_dir=tmp_path)
    assert result.status is RunStatus.SUCCEEDED
    assert result.execution_mode is domain.ExecutionMode.BATCH
    simulation = result.simulation
    assert simulation is not None and simulation.raw_artifact_reference is not None
    assert [(m.name, m.value, m.unit) for m in simulation.metrics] == [
        ("company_money", 7858, "GBP"),
        ("company_loan", 290000, "GBP"),
        ("current_period_income", 12, "GBP"),
        ("current_period_expenses", -1026, "GBP"),
        ("current_period_cargo_delivered", 7, "cargo_units"),
    ]
    (experiment,) = captured["experiments"]
    assert set(experiment) == {"seed", "ais", "days", "openttd_config"}
    assert experiment["seed"] == 314 and experiment["days"] == 90
    artifact_path = Path(simulation.raw_artifact_reference)
    assert artifact_path == tmp_path / f"experiment-{result.run_id}.json.gz"
    with gzip.open(artifact_path, "rt", encoding="utf-8") as stream:
        artifact = json.load(stream)
    assert set(artifact) == {
        "configuration",
        "date",
        "savegame_version",
        "chunks",
        "output",
        "error",
    }
    assert artifact["configuration"] == config.model_dump(mode="json")
    assert set(artifact["configuration"]) == {
        "scenario",
        "planning",
        "ai",
        "openttd_version",
        "opengfx_version",
        "seed",
        "duration_days",
    }
    assert artifact["date"] == "1950-12-01"
    assert artifact["chunks"] == parsed_row(config)["chunks"]
    assert set(result.model_dump()["simulation"]) == {
        "simulation_date",
        "savegame_version",
        "metrics",
        "raw_artifact_reference",
    }
    with session_factory() as session:
        run = session.get(ExperimentRunRecord, result.run_id)
        assert run is not None and run.simulation is not None
        assert {(m.name, float(m.value), m.unit) for m in run.simulation.metrics} == {
            (m.name, m.value, m.unit) for m in simulation.metrics
        }
