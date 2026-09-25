"""THROWAWAY Linux launch seam, confined to one OpenTTDLab pool worker.

No installed library files are edited. OpenTTDLab owns setup, AI, autosaves and parsing.
The stock null video driver cannot host Admin Network; select dedicated instead.
"""

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import openttdlab

STOCK_RUN_EXPERIMENT = openttdlab._run_experiment


def dedicated_arguments(args):
    if sum(arg.startswith("-vnull:ticks=") for arg in args) != 1:
        raise RuntimeError("Unexpected OpenTTDLab launch shape")
    return tuple(arg for arg in args if not arg.startswith("-vnull:ticks=")) + (
        f"-D127.0.0.1:{os.environ['PROTOTYPE_GAME_PORT']}",
        "-dnet=0",
        "-x",
    )


def dedicated_check_output(args, **kwargs):
    config_path = Path(args[args.index("-c") + 1])
    # Lab generates an unversioned config: 13.4's pre-private/secrets migration
    # reads password settings from this file. Never inject into ExperimentConfig,
    # which the existing adapter serializes into its final artifact.
    configuration = config_path.read_text()
    if configuration.count("[network]\n") != 1:
        raise RuntimeError("Expected exactly one network section")
    config_path.write_text(
        configuration.replace(
            "[network]\n",
            "[network]\nadmin_password = " + os.environ["PROTOTYPE_ADMIN_PASSWORD"] + "\n",
            1,
        )
    )
    config_path.chmod(0o600)
    args = dedicated_arguments(args)
    (Path(os.environ["PROTOTYPE_OUTPUT"]) / "launch.json").write_text(
        __import__("json").dumps({"pid_owner": os.getpid(), "args": args}, indent=2)
    )
    # Inherit the supervisor's process group so its cancellation kills descendants.
    with subprocess.Popen(args, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, **kwargs) as proc:
        try:
            output, _ = proc.communicate(timeout=540)
        except BaseException:
            proc.terminate()
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
            raise
        if proc.returncode:
            # Avoid including captured output/config secrets in exceptions.
            raise RuntimeError(f"OpenTTD exited with code {proc.returncode}")
        return output


def run_dedicated_experiment(*args):
    original = openttdlab.subprocess
    openttdlab.subprocess = SimpleNamespace(
        check_output=dedicated_check_output, STDOUT=subprocess.STDOUT
    )
    try:
        return STOCK_RUN_EXPERIMENT(*args)
    finally:
        openttdlab.subprocess = original


def main():
    import json

    from app.experiments.domain import ExperimentConfig, ScenarioConfig
    from app.experiments.strategies import SimpleRoadOnlyStrategy
    from app.simulation.openttd.runner import OpenTTDLabRunner

    if openttdlab.__version__ != "0.0.75":
        raise RuntimeError("This seam requires OpenTTDLab 0.0.75")
    output = Path(os.environ["PROTOTYPE_OUTPUT"])
    scenario = ScenarioConfig(
        identifier="prototype-live-admin",
        version="throwaway-1",
        openttd_config=(
            "[game_creation]\nmap_x = 8\nmap_y = 8\nstarting_year = 1950\n"
            "[network]\nserver_name = Live telemetry prototype\n"
            f"server_admin_port = {os.environ['PROTOTYPE_ADMIN_PORT']}\n"
            "server_game_type = local\nmin_active_clients = 0\n"
            "[ai]\nai_in_multiplayer = true\n"
        ),
    )
    planning, ai = SimpleRoadOnlyStrategy().configure(scenario)
    config = ExperimentConfig(
        scenario=scenario,
        planning=planning,
        ai=ai,
        openttd_version="13.4",
        opengfx_version="7.1",
        seed=17,
        duration_days=120,
    )
    openttdlab._run_experiment = run_dedicated_experiment
    result = OpenTTDLabRunner().run(config, run_id=1, artifact_dir=output)
    (output / "final-result.json").write_text(json.dumps(result.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
