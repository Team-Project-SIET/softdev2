"""Real owned runner lifecycle against a Python controlled peer; zero OpenTTD."""

from dataclasses import replace
from pathlib import Path

from app.experiments.plan_service import runtime_config
from app.simulation.openttd.admin_observer import ExpectedServerIdentity
from app.simulation.openttd.live_launch import LiveLaunchPreparation
from app.simulation.openttd.live_runner import LiveSimulationRunner
from app.simulation.openttd.plan_setup import PlanSetup
from app.simulation.openttd.runtime_assets import AcquisitionPolicy, PinnedRuntimePreparer
from tests.test_live_runner import _fixture_result, _options, _runtime
from tests.test_plan_evaluation import plan_world, request
from tests.test_planning_execution import run_executor


def test_plan_setup_then_original_horizon_then_final_save(tmp_path: Path):
    value = plan_world(request(), tmp_path / "world.sav")
    config = runtime_config(value)
    runtime = replace(_runtime(tmp_path, "plan_evaluation"), ai_configuration=config.ai)
    log, _ = run_executor(value.plan, value.scenario, value.bindings)
    (runtime.executable_path.parent / "execution.log").write_text(log)

    class Assets(PinnedRuntimePreparer):
        def prepare(
            self,
            config,
            *,
            deadline=None,
            acquisition_policy=AcquisitionPolicy.CACHE_ONLY,
            plan_package=False,
        ):
            assert plan_package is True
            return runtime

    class Launch(LiveLaunchPreparation):
        prepared = None

        def prepare(self, *args, **kwargs):
            self.prepared = super().prepare(*args, **kwargs)
            return self.prepared

    launch = Launch(tmp_path / "workspaces", lock_root=tmp_path / "locks").for_plan(
        value, tmp_path / "world.sav"
    )
    setup = PlanSetup(value)
    observed = []

    async def final_result(prepared, progress, config):
        observed.append(progress)
        return await _fixture_result(prepared, progress, config)

    runner = LiveSimulationRunner(
        Assets(tmp_path / "cache"),
        launch,
        expected_identity=ExpectedServerIdentity("13.4", 17, "", 64, 64, 0),
        options=_options(),
        final_result=final_result,
        plan_setup=setup,
    )
    artifacts = tmp_path / "run-1"
    artifacts.mkdir()
    try:
        result = runner.run(config, run_id=1, artifact_dir=artifacts)
    except Exception as error:
        raise AssertionError(
            f"setup_start={setup.observed_start_day}; failure={getattr(error, 'failure', None)}"
        ) from None
    assert setup.receipt is not None
    assert setup.receipt.result == "success"
    assert observed[0].target_day == setup.observed_start_day + value.scenario.horizon_days
    assert observed[0].last_observed_day >= observed[0].target_day
    assert result.live_summary is not None
    assert result.live_summary.process_exit_code == 0
    assert launch.prepared is not None
    assert not launch.prepared.workspace.exists()
    assert (artifacts / "execution-evidence.log").exists()
    assert (artifacts / "runtime-provenance.json").exists()
