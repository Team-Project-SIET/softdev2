"""Controlled child and Admin peer prove T07 lifecycle without OpenTTD or SQL."""

import asyncio
import fcntl
import hashlib
import os
import shutil
import signal
import socket
import stat
import threading
import time
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from test_runtime_assets import _fixture_assets, _LocalSource, _tar

from app.experiments.domain import (
    ExecutionFailureCode,
    ExperimentConfig,
    LiveExecutionOptions,
    Metric,
    ScenarioConfig,
    SimulationExecutionError,
    SimulationResult,
)
from app.experiments.strategies import SimpleRoadOnlyStrategy
from app.simulation.openttd.admin_observer import ExpectedServerIdentity
from app.simulation.openttd.live_launch import LiveLaunchPreparation, PreparedLiveRuntime
from app.simulation.openttd.runtime_assets import (
    AcquisitionPolicy,
    PinnedRuntimePreparer,
    PreparedRuntime,
    RuntimePreparationCode,
    RuntimePreparationError,
)


def _config() -> ExperimentConfig:
    scenario = ScenarioConfig(
        identifier="controlled",
        version="1",
        openttd_config="[game_creation]\nmap_x = 8\nmap_y = 8\n",
    )
    planning, ai = SimpleRoadOnlyStrategy().configure(scenario)
    return ExperimentConfig(
        scenario=scenario,
        planning=planning,
        ai=ai,
        openttd_version="13.4",
        opengfx_version="7.1",
        seed=17,
        duration_days=30,
    )


class _Assets:
    def __init__(self, runtime: PreparedRuntime) -> None:
        self.runtime = runtime
        self.calls = 0

    def prepare(
        self,
        config: ExperimentConfig,
        *,
        deadline: float | None = None,
        acquisition_policy: AcquisitionPolicy = AcquisitionPolicy.ALLOW_PROVISIONING,
    ) -> PreparedRuntime:
        self.calls += 1
        assert config == _config()
        assert deadline is not None
        assert acquisition_policy is AcquisitionPolicy.CACHE_ONLY
        return self.runtime


def _runtime(tmp_path: Path, mode: str) -> PreparedRuntime:
    cache = tmp_path / "cache"
    cache.mkdir()
    executable = cache / "openttd"
    shutil.copyfile(Path(__file__).parent / "fixtures/controlled_live_server.py", executable)
    executable.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    (cache / "mode.txt").write_text(mode)
    gfx = cache / "opengfx-7.1.tar"
    ai = cache / "SimpleAI-14.tar"
    for path in (gfx, ai):
        path.write_bytes(b"fixture")
    return PreparedRuntime(
        executable_path=executable,
        opengfx_archive_path=gfx,
        ai_archive_path=ai,
        dependency_archive_paths=(),
        ai_configuration=_config().ai,
        provenance={"cache_identity": "controlled-fixture"},
    )


def _verified_cache(tmp_path: Path) -> tuple[PinnedRuntimePreparer, _LocalSource]:
    pins, blobs = _fixture_assets(dependencies=True)
    child = (Path(__file__).parent / "fixtures/controlled_live_server.py").read_bytes()
    root = "openttd-13.4-linux-generic-amd64/"
    blobs["openttd"] = _tar(
        {root + "openttd": child, root + "lib/mode.txt": b"normal"},
        compression="xz",
    )
    pins["openttd"] = replace(pins["openttd"], sha256=hashlib.sha256(blobs["openttd"]).hexdigest())
    source = _LocalSource(blobs)
    assets = PinnedRuntimePreparer(tmp_path / "cache", source=source, pins=pins)
    assets.prepare(_config())
    return assets, source


def _identity() -> ExpectedServerIdentity:
    return ExpectedServerIdentity("OpenTTD 13.4", 17, "", 256, 256, 0)


def _options(**changes) -> LiveExecutionOptions:
    values = dict(
        startup_timeout_seconds=3,
        handshake_timeout_seconds=1,
        running_timeout_seconds=1,
        shutdown_timeout_seconds=0.5,
        terminate_timeout_seconds=0.5,
        kill_timeout_seconds=0.5,
        final_parse_timeout_seconds=1,
    )
    values.update(changes)
    return LiveExecutionOptions(**values)


class _Launch:
    def __init__(self, preparation: LiveLaunchPreparation) -> None:
        self.preparation = preparation
        self.prepared = None

    def prepare(self, config, runtime, *, deadline=None):
        self.prepared = self.preparation.prepare(config, runtime, deadline=deadline)
        return self.prepared


async def _fixture_result(prepared, progress, request_save) -> SimulationResult:
    return SimulationResult(
        simulation_date=date(1950, 1, 31),
        savegame_version=1,
        metrics=(Metric(name="fixture", value=1, unit="count"),),
    )


def _make_runner(tmp_path: Path, mode: str, *, final_result=_fixture_result, options=None):
    from app.simulation.openttd.live_runner import LiveSimulationRunner

    runtime = _runtime(tmp_path, mode)
    launch = _Launch(LiveLaunchPreparation(tmp_path / "runs", lock_root=tmp_path / "locks"))
    runner = LiveSimulationRunner(
        _Assets(runtime),
        launch,
        expected_identity=_identity(),
        final_result=final_result,
        options=options or _options(),
    )
    return runner, launch


def test_one_owned_child_reaches_date_target_and_returns_injected_final_result(
    tmp_path: Path, monkeypatch
) -> None:
    from app.simulation.openttd.live_runner import LiveSimulationRunner

    runtime = _runtime(tmp_path, "normal")
    assets = _Assets(runtime)
    launch = LiveLaunchPreparation(tmp_path / "runs", lock_root=tmp_path / "locks")
    final_calls = []
    commands_seen: list[str] = []
    original_close = PreparedLiveRuntime.close

    def capture_then_close(prepared):
        commands_seen.extend((prepared.workspace / "commands.log").read_text().splitlines())
        return original_close(prepared)

    monkeypatch.setattr(PreparedLiveRuntime, "close", capture_then_close)

    async def final_result(prepared, progress, request_save):
        final_calls.append((prepared, progress))
        await request_save()
        return SimulationResult(
            simulation_date=date(1950, 1, 31),
            savegame_version=1,
            metrics=(Metric(name="fixture", value=1, unit="count"),),
        )

    launches = []
    original = __import__("asyncio").create_subprocess_exec

    async def count_launch(*args, **kwargs):
        launches.append((args, kwargs))
        return await original(*args, **kwargs)

    monkeypatch.setattr("asyncio.create_subprocess_exec", count_launch)
    runner = LiveSimulationRunner(
        assets,
        launch,
        expected_identity=_identity(),
        final_result=final_result,
        options=_options(),
    )
    result = runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")

    assert assets.calls == 1
    assert len(launches) == 1
    args, kwargs = launches[0]
    assert args[0] == str(runtime.executable_path)
    assert kwargs["start_new_session"] is True
    assert "shell" not in kwargs
    assert final_calls[0][1].observed_start_day == date(1950, 1, 1).toordinal() + 365
    assert final_calls[0][1].target_day == date(1950, 1, 1).toordinal() + 365 + 30
    assert result.live_summary is not None
    assert result.live_summary.last_observed_day == final_calls[0][1].target_day
    assert result.live_summary.cleanup_succeeded is True
    assert commands_seen == ["unpause", "pause", "save final.sav", "quit"]
    assert not final_calls[0][0].workspace.exists()
    assert final_calls[0][0].lease.closed


@pytest.mark.parametrize(
    ("mode", "reason"),
    [
        ("bad_auth", ExecutionFailureCode.AUTHENTICATION_FAILURE),
        ("bad_protocol", ExecutionFailureCode.PROTOCOL_FAILURE),
        ("wrong_identity", ExecutionFailureCode.PROTOCOL_FAILURE),
        ("eof_after_ready", ExecutionFailureCode.UNEXPECTED_SHUTDOWN),
        ("shutdown_after_ready", ExecutionFailureCode.UNEXPECTED_SHUTDOWN),
        ("malformed_after_ready", ExecutionFailureCode.PROTOCOL_FAILURE),
        ("exit_early", ExecutionFailureCode.UNEXPECTED_SHUTDOWN),
    ],
)
def test_observer_or_child_failure_stops_only_owned_process_and_cleans_resources(
    tmp_path: Path, monkeypatch, mode: str, reason: ExecutionFailureCode
) -> None:
    runner, launch = _make_runner(tmp_path, mode)
    child_pids: list[int] = []
    signals: list[int] = []
    original_spawn = asyncio.create_subprocess_exec
    original_signal = os.killpg

    async def spawn(*args, **kwargs):
        child = await original_spawn(*args, **kwargs)
        child_pids.append(child.pid)
        return child

    def signal_group(pid: int, requested: int):
        signals.append(pid)
        return original_signal(pid, requested)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(os, "killpg", signal_group)
    with pytest.raises(SimulationExecutionError) as error:
        runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")
    assert error.value.failure.code is reason
    assert len(child_pids) == 1
    assert all(pid == child_pids[0] for pid in signals)
    with pytest.raises(ProcessLookupError):
        os.kill(child_pids[0], 0)
    assert launch.prepared.lease.closed
    assert not launch.prepared.workspace.exists()


@pytest.mark.parametrize(
    ("mode", "options", "reason"),
    [
        ("missing_udp", _options(startup_timeout_seconds=0.2), ExecutionFailureCode.TIMEOUT),
        ("no_date", _options(handshake_timeout_seconds=0.2), ExecutionFailureCode.TIMEOUT),
        ("no_target", _options(running_timeout_seconds=0.2), ExecutionFailureCode.TIMEOUT),
        ("hang_on_quit", _options(shutdown_timeout_seconds=0.2), ExecutionFailureCode.TIMEOUT),
    ],
)
def test_startup_running_and_shutdown_deadlines_are_bounded(
    tmp_path: Path, mode: str, options: LiveExecutionOptions, reason: ExecutionFailureCode
) -> None:
    runner, launch = _make_runner(tmp_path, mode, options=options)
    with pytest.raises(SimulationExecutionError) as error:
        runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")
    assert error.value.failure.code is reason
    assert launch.prepared.lease.closed
    assert not launch.prepared.workspace.exists()


def test_overshoot_is_recorded_without_claiming_final_save_date(tmp_path: Path) -> None:
    runner, _ = _make_runner(tmp_path, "overshoot")
    result = runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")
    assert result.live_summary is not None
    assert result.live_summary.last_observed_day == date(1950, 1, 1).toordinal() + 365 + 32
    assert result.live_summary.requested_target_day == date(1950, 1, 1).toordinal() + 365 + 30
    assert result.live_summary.actual_final_day is None


def test_large_stdout_and_stderr_cannot_deadlock_child(tmp_path: Path) -> None:
    runner, launch = _make_runner(tmp_path, "large_output")
    result = runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")
    assert result.live_summary is not None
    assert launch.prepared.lease.closed


def test_final_result_failure_cannot_become_success(tmp_path: Path) -> None:
    async def broken(_prepared, _progress, _request_save):
        raise OSError("private save path and secret")

    runner, launch = _make_runner(tmp_path, "normal", final_result=broken)
    with pytest.raises(SimulationExecutionError) as error:
        runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")
    assert error.value.failure.code is ExecutionFailureCode.FINALIZATION_FAILURE
    assert "private save" not in str(error.value)
    assert launch.prepared.lease.closed


def test_production_runner_requires_explicit_final_result_operation(tmp_path: Path) -> None:
    from app.simulation.openttd.live_runner import LiveSimulationRunner

    runtime = _runtime(tmp_path, "normal")
    launch = LiveLaunchPreparation(tmp_path / "runs", lock_root=tmp_path / "locks")
    with pytest.raises(TypeError):
        LiveSimulationRunner(_Assets(runtime), launch, expected_identity=_identity())
    assert not (tmp_path / "runs").exists()


def test_cancellation_reaps_owned_child_and_releases_lease(tmp_path: Path, monkeypatch) -> None:
    from app.simulation.openttd.live_runner import LiveSimulationRunner

    runtime = _runtime(tmp_path, "no_target")
    launch = _Launch(LiveLaunchPreparation(tmp_path / "runs", lock_root=tmp_path / "locks"))
    cancel = threading.Event()
    started = threading.Event()
    child_pids: list[int] = []
    failures: list[SimulationExecutionError] = []
    original_spawn = asyncio.create_subprocess_exec

    async def spawn(*args, **kwargs):
        child = await original_spawn(*args, **kwargs)
        child_pids.append(child.pid)
        started.set()
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    runner = LiveSimulationRunner(
        _Assets(runtime),
        launch,
        expected_identity=_identity(),
        final_result=_fixture_result,
        options=_options(running_timeout_seconds=3),
        cancellation=cancel,
    )

    def execute() -> None:
        try:
            runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")
        except SimulationExecutionError as exc:
            failures.append(exc)

    worker = threading.Thread(target=execute)
    worker.start()
    try:
        assert started.wait(2)
        cancel.set()
        worker.join(2)
        assert not worker.is_alive()
        assert failures[0].failure.code is ExecutionFailureCode.CANCELLED
        with pytest.raises(ProcessLookupError):
            os.kill(child_pids[0], 0)
        assert launch.prepared.lease.closed
        assert not launch.prepared.workspace.exists()
    finally:
        cancel.set()
        worker.join(5)


def test_forced_stop_signals_only_owned_group_before_lease_release(
    tmp_path: Path, monkeypatch
) -> None:
    runner, launch = _make_runner(
        tmp_path,
        "ignore_term",
        options=_options(shutdown_timeout_seconds=0.1, terminate_timeout_seconds=0.1),
    )
    child_pids: list[int] = []
    signals: list[tuple[int, int]] = []
    close_after_reap: list[bool] = []
    original_spawn = asyncio.create_subprocess_exec
    original_signal = os.killpg
    original_close = PreparedLiveRuntime.close

    async def spawn(*args, **kwargs):
        child = await original_spawn(*args, **kwargs)
        child_pids.append(child.pid)
        assert os.getpgid(child.pid) == child.pid
        return child

    def signal_group(pid: int, requested: int):
        signals.append((pid, requested))
        return original_signal(pid, requested)

    def close(prepared):
        with pytest.raises(ProcessLookupError):
            os.kill(child_pids[0], 0)
        close_after_reap.append(True)
        return original_close(prepared)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(os, "killpg", signal_group)
    monkeypatch.setattr(PreparedLiveRuntime, "close", close)
    with pytest.raises(SimulationExecutionError) as error:
        runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")
    assert error.value.failure.code is ExecutionFailureCode.TIMEOUT
    assert signals == [(child_pids[0], signal.SIGTERM), (child_pids[0], signal.SIGKILL)]
    assert close_after_reap == [True]
    assert launch.prepared.lease.closed


def test_cancellation_interrupts_finalization_without_returning_success(
    tmp_path: Path,
) -> None:
    entered = threading.Event()
    cancel = threading.Event()
    failures: list[SimulationExecutionError] = []

    async def stalled(_prepared, _progress, _request_save):
        entered.set()
        await asyncio.Event().wait()

    runner, launch = _make_runner(
        tmp_path,
        "normal",
        final_result=stalled,
        options=_options(final_parse_timeout_seconds=3),
    )
    runner.cancellation = cancel

    def execute() -> None:
        try:
            runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")
        except SimulationExecutionError as exc:
            failures.append(exc)

    worker = threading.Thread(target=execute)
    worker.start()
    try:
        assert entered.wait(2)
        cancel.set()
        worker.join(2)
        assert not worker.is_alive()
        assert failures[0].failure.code is ExecutionFailureCode.CANCELLED
        assert launch.prepared.lease.closed
        assert not launch.prepared.workspace.exists()
    finally:
        cancel.set()
        worker.join(5)


def test_observer_shutdown_interrupts_stalled_finalization(tmp_path: Path) -> None:
    async def stalled(_prepared, _progress, _request_save):
        await asyncio.Event().wait()

    runner, launch = _make_runner(
        tmp_path,
        "shutdown_on_pause",
        final_result=stalled,
        options=_options(final_parse_timeout_seconds=3),
    )
    started = time.monotonic()
    with pytest.raises(SimulationExecutionError) as error:
        runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")
    assert time.monotonic() - started < 2
    assert error.value.failure.code is ExecutionFailureCode.UNEXPECTED_SHUTDOWN
    assert launch.prepared.lease.closed


def test_prelaunch_cleanup_error_preserves_original_failure(tmp_path: Path, monkeypatch) -> None:
    from app.simulation.openttd.live_runner import LiveSimulationRunner

    runtime = _runtime(tmp_path, "normal")
    launch = _Launch(LiveLaunchPreparation(tmp_path / "runs", lock_root=tmp_path / "locks"))

    def broken_close(prepared):
        prepared.lease.close()
        raise OSError("sensitive workspace path")

    monkeypatch.setattr(PreparedLiveRuntime, "close", broken_close)
    runner = LiveSimulationRunner(
        _Assets(runtime),
        launch,
        expected_identity=ExpectedServerIdentity("wrong", 17, "", 256, 256, 0),
        final_result=_fixture_result,
        options=_options(),
    )
    with pytest.raises(SimulationExecutionError) as error:
        runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")
    assert error.value.failure.code is ExecutionFailureCode.PROTOCOL_FAILURE
    assert error.value.failure.cleanup_diagnostics == ("workspace_or_lease_cleanup_failure",)
    assert "sensitive" not in str(error.value)


def test_signal_error_does_not_skip_later_cleanup(tmp_path: Path, monkeypatch) -> None:
    runner, launch = _make_runner(
        tmp_path,
        "ignore_term",
        options=_options(shutdown_timeout_seconds=0.1, terminate_timeout_seconds=0.1),
    )
    original_signal = os.killpg
    requested_signals: list[int] = []

    def flaky_signal(pid: int, requested: int):
        requested_signals.append(requested)
        if requested == signal.SIGTERM:
            raise PermissionError("private process detail")
        return original_signal(pid, requested)

    monkeypatch.setattr(os, "killpg", flaky_signal)
    with pytest.raises(SimulationExecutionError) as error:
        runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")
    assert error.value.failure.code is ExecutionFailureCode.TIMEOUT
    assert "owned_process_term_error" in error.value.failure.cleanup_diagnostics
    assert signal.SIGKILL in requested_signals
    assert "private process" not in str(error.value)
    assert launch.prepared.lease.closed
    assert not launch.prepared.workspace.exists()


def test_cache_lock_contention_exhausts_startup_without_launching_openttd(
    tmp_path: Path, monkeypatch
) -> None:
    from app.simulation.openttd.live_runner import LiveSimulationRunner

    cache = tmp_path / "cache" / "openttd-13.4-pinned-v1"
    cache.mkdir(parents=True)
    launch = _Launch(LiveLaunchPreparation(tmp_path / "runs", lock_root=tmp_path / "locks"))
    launches = []

    async def forbidden_launch(*args, **kwargs):
        launches.append((args, kwargs))
        raise AssertionError("OpenTTD must not launch after cache lock timeout")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden_launch)
    runner = LiveSimulationRunner(
        PinnedRuntimePreparer(tmp_path / "cache"),
        launch,
        expected_identity=_identity(),
        final_result=_fixture_result,
        options=_options(startup_timeout_seconds=0.15),
    )
    with (cache / ".prepare.lock").open("a+b") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX)
        try:
            started = time.monotonic()
            with pytest.raises(SimulationExecutionError) as error:
                runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")
            assert time.monotonic() - started < 1
        finally:
            fcntl.flock(holder, fcntl.LOCK_UN)
    assert error.value.failure.code is ExecutionFailureCode.TIMEOUT
    assert launches == []
    assert launch.prepared is None
    assert sorted(path.name for path in cache.iterdir()) == [".prepare.lock"]


@pytest.mark.parametrize(
    "preparation_code",
    [RuntimePreparationCode.MISSING_ASSET, RuntimePreparationCode.CHECKSUM_MISMATCH],
)
def test_cache_only_asset_failure_never_launches_process(
    tmp_path: Path, monkeypatch, preparation_code: RuntimePreparationCode
) -> None:
    from app.simulation.openttd.live_runner import LiveSimulationRunner

    class FailingAssets:
        def prepare(self, config, *, deadline, acquisition_policy):
            assert config == _config()
            assert deadline > time.monotonic()
            assert acquisition_policy is AcquisitionPolicy.CACHE_ONLY
            raise RuntimePreparationError(preparation_code)

    launches = []

    async def forbidden_launch(*args, **kwargs):
        launches.append((args, kwargs))
        raise AssertionError("process launched after asset failure")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden_launch)
    launch = _Launch(LiveLaunchPreparation(tmp_path / "runs", lock_root=tmp_path / "locks"))
    runner = LiveSimulationRunner(
        FailingAssets(),
        launch,
        expected_identity=_identity(),
        final_result=_fixture_result,
        options=_options(),
    )
    with pytest.raises(SimulationExecutionError) as error:
        runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")
    assert error.value.failure.code is ExecutionFailureCode.STARTUP_FAILURE
    assert launches == []
    assert launch.prepared is None


def test_runner_uses_verified_cache_without_reaching_asset_fetcher(
    tmp_path: Path, monkeypatch
) -> None:
    from app.simulation.openttd.live_runner import LiveSimulationRunner

    assets, source = _verified_cache(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("live startup attempted asset acquisition")

    monkeypatch.setattr(source, "fetch", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    launch = _Launch(LiveLaunchPreparation(tmp_path / "runs", lock_root=tmp_path / "locks"))
    runner = LiveSimulationRunner(
        assets,
        launch,
        expected_identity=_identity(),
        final_result=_fixture_result,
        options=_options(),
    )
    result = runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")
    assert result.live_summary is not None
    assert result.live_summary.cleanup_succeeded is True
    assert launch.prepared.lease.closed


@pytest.mark.parametrize(
    "invalid", ["openttd", "opengfx", "simpleai", "pathfinder_road", "corrupt"]
)
def test_runner_rejects_missing_or_corrupt_cached_asset_before_launch(
    tmp_path: Path, monkeypatch, invalid: str
) -> None:
    from app.simulation.openttd.live_runner import LiveSimulationRunner

    assets, source = _verified_cache(tmp_path)
    root = tmp_path / "cache" / "openttd-13.4-pinned-v1"
    if invalid == "corrupt":
        (root / "openttd" / "archive").write_bytes(b"corrupt")
    else:
        shutil.rmtree(root / invalid)
    launches = []

    def forbidden(*args, **kwargs):
        raise AssertionError("cache-only startup reached the network")

    async def forbidden_launch(*args, **kwargs):
        launches.append((args, kwargs))
        raise AssertionError("OpenTTD launched with missing runtime asset")

    monkeypatch.setattr(source, "fetch", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden_launch)
    launch = _Launch(LiveLaunchPreparation(tmp_path / "runs", lock_root=tmp_path / "locks"))
    runner = LiveSimulationRunner(
        assets,
        launch,
        expected_identity=_identity(),
        final_result=_fixture_result,
        options=_options(),
    )
    with pytest.raises(SimulationExecutionError) as error:
        runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")
    assert error.value.failure.code is ExecutionFailureCode.STARTUP_FAILURE
    assert launches == []
    assert launch.prepared is None
