"""Thin, replaceable OpenTTDLab adapter and savegame metric extraction."""

import gzip
import json
import os
import tempfile
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from app.experiments.domain import ExperimentConfig, Metric, SimulationResult


class SimulationRunner(Protocol):
    def run(
        self, config: ExperimentConfig, *, run_id: int, artifact_dir: Path
    ) -> SimulationResult: ...


def parse_result_row(row: dict[str, Any], config: ExperimentConfig) -> SimulationResult:
    """Translate the known OpenTTDLab 0.0.75 savegame shape at one boundary."""

    if row.get("error"):
        raise RuntimeError("OpenTTD reported an AI script failure")
    if row.get("openttd_version") != config.openttd_version:
        raise ValueError("OpenTTDLab returned a different OpenTTD version")
    if row.get("opengfx_version") != config.opengfx_version:
        raise ValueError("OpenTTDLab returned a different OpenGFX version")
    experiment = row["experiment"]
    if experiment["seed"] != config.seed or experiment["days"] != config.duration_days:
        raise ValueError("OpenTTDLab returned data for a different experiment")
    player = row["chunks"]["PLYR"]["0"]
    economy = player["cur_economy"][0]
    simulation_date = row["date"]
    if isinstance(simulation_date, str):
        simulation_date = date.fromisoformat(simulation_date)
    return SimulationResult(
        simulation_date=simulation_date,
        savegame_version=row["savegame_version"],
        metrics=(
            Metric(name="company_money", value=player["money"], unit="GBP"),
            Metric(name="company_loan", value=player["current_loan"], unit="GBP"),
            Metric(name="current_period_income", value=economy["income"], unit="GBP"),
            Metric(name="current_period_expenses", value=economy["expenses"], unit="GBP"),
            Metric(
                name="current_period_cargo_delivered",
                value=sum(economy["delivered_cargo"]),
                unit="cargo_units",
            ),
        ),
    )


def write_parsed_artifact(
    row: dict[str, Any],
    config: ExperimentConfig,
    result: SimulationResult,
    *,
    run_id: int,
    artifact_dir: Path,
    replace_existing: bool = True,
) -> Path:
    """Write the existing batch gzip/JSON shape for either final-save path."""
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / f"experiment-{run_id}.json.gz"
    with tempfile.NamedTemporaryFile(dir=artifact_dir, delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with gzip.open(temporary_path, "wt", encoding="utf-8") as artifact:
            json.dump(
                {
                    "configuration": config.model_dump(mode="json"),
                    "date": result.simulation_date.isoformat(),
                    "savegame_version": row["savegame_version"],
                    "chunks": row["chunks"],
                    "output": row.get("output"),
                    "error": row["error"],
                },
                artifact,
                default=str,
            )
        if replace_existing:
            os.replace(temporary_path, artifact_path)
        else:
            os.link(temporary_path, artifact_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return artifact_path


class OpenTTDLabRunner:
    def __init__(self, run_experiments: Callable[..., list[dict[str, Any]]] | None = None) -> None:
        if run_experiments is None:
            from openttdlab import run_experiments as library_run_experiments

            run_experiments = library_run_experiments
        self.run_experiments = run_experiments

    def run(self, config: ExperimentConfig, *, run_id: int, artifact_dir: Path) -> SimulationResult:
        from openttdlab import bananas_ai

        artifact_dir.mkdir(parents=True, exist_ok=True)
        cache_dir = artifact_dir / "cache"
        cache_dir.mkdir(exist_ok=True)
        ai = bananas_ai(
            config.ai.content_id,
            config.ai.name,
            ai_params=config.ai.parameters,
            md5=config.ai.md5,
        )
        rows = self.run_experiments(
            experiments=(
                {
                    "seed": config.seed,
                    "ais": (ai,),
                    "days": config.duration_days,
                    "openttd_config": config.scenario.openttd_config,
                },
            ),
            openttd_version=config.openttd_version,
            opengfx_version=config.opengfx_version,
            max_workers=1,
            get_cache_dir=lambda: str(cache_dir),
        )
        if not rows:
            raise RuntimeError("OpenTTDLab returned no parsed savegame snapshots")
        if any(row.get("error") for row in rows):
            raise RuntimeError("OpenTTD reported an AI script failure")
        final_row = max(rows, key=lambda row: row["date"])
        result = parse_result_row(final_row, config)
        artifact_path = write_parsed_artifact(
            final_row, config, result, run_id=run_id, artifact_dir=artifact_dir
        )
        return result.model_copy(update={"raw_artifact_reference": str(artifact_path.resolve())})
