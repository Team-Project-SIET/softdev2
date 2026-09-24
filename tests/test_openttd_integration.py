from pathlib import Path

import pytest

from app.experiments.domain import ExperimentConfig, ScenarioConfig
from app.experiments.strategies import BaselineStrategy
from app.simulation.openttd.runner import OpenTTDLabRunner


@pytest.mark.openttd
def test_real_fixed_seed_simulation(request: pytest.FixtureRequest, tmp_path: Path) -> None:
    if not request.config.getoption("--run-openttd"):
        pytest.skip("pass --run-openttd to run the headless OpenTTD integration test")

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
        seed=17,
        duration_days=365,
    )
    result = OpenTTDLabRunner().run(config, run_id=1, artifact_dir=tmp_path)

    assert result.simulation_date.year == 1950
    assert Path(result.raw_artifact_reference).is_file()
    metrics = {metric.name: metric.value for metric in result.metrics}
    assert metrics["company_money"] >= 0
    assert metrics["company_loan"] >= 0
