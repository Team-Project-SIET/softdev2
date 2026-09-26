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
    def __init__(
        self, runtime: PreparedRuntime, expected_config: ExperimentConfig | None = None
    ) -> None:
        self.runtime = runtime
        self.expected_config = expected_config or _config()
        self.calls = 0

    def prepare(
        self,
        config: ExperimentConfig,
        *,
        deadline: float | None = None,
        acquisition_policy: AcquisitionPolicy = AcquisitionPolicy.ALLOW_PROVISIONING,
    ) -> PreparedRuntime:
        self.calls += 1
        assert config == self.expected_config
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
    if mode == "save_valid_fixture":
        shutil.copyfile(
            Path(__file__).parent / "fixtures/openttd_13_4/seed-17-simpleai-road.sav",
            cache / "static.sav",
        )
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
    return ExpectedServerIdentity("13.4", 17, "", 256, 256, 0)


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


async def _fixture_result(prepared, progress, config) -> SimulationResult:
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

    async def final_result(prepared, progress, config):
        final_calls.append((prepared, progress))
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
    assert commands_seen == [
        "exec scripts/live_unpause_barrier.scr",
        "exec scripts/live_pause_barrier.scr",
        "save final",
        "quit",
    ]
    assert not final_calls[0][0].workspace.exists()
    assert final_calls[0][0].lease.closed


def test_observer_events_reach_one_scoped_telemetry_processor(tmp_path: Path) -> None:
    from app.simulation.openttd.live_runner import LiveSimulationRunner
    from app.simulation.openttd.telemetry import ObservationKind
    from app.simulation.openttd.telemetry_processor import TelemetryProcessor

    class RecordingStore:
        def __init__(self):
            self.batches = []
            self.closed = False

        async def write_batch(self, batch, *, deadline):
            self.batches.append(batch)

        async def close(self):
            self.closed = True

    store = RecordingStore()
    runtime = _runtime(tmp_path, "normal")
    runner = LiveSimulationRunner(
        _Assets(runtime),
        LiveLaunchPreparation(tmp_path / "runs", lock_root=tmp_path / "locks"),
        expected_identity=_identity(),
        final_result=_fixture_result,
        options=_options(),
        telemetry_factory=lambda run_id: TelemetryProcessor(run_id, store),
    )
    result = runner.run(_config(), run_id=7, artifact_dir=tmp_path / "artifacts")
    assert result.live_summary is not None
    assert store.closed
    rows = [row for batch in store.batches for row in batch.observations]
    assert [row.sequence for row in rows] == list(range(1, len(rows) + 1))
    assert all(row.experiment_run_id == 7 for row in rows)
    assert sum(row.kind is ObservationKind.DATE for row in rows) >= 2


def test_fatal_telemetry_write_cannot_return_live_success(tmp_path: Path) -> None:
    from app.experiments.telemetry_repository import PermanentStorageError
    from app.simulation.openttd.live_runner import LiveSimulationRunner
    from app.simulation.openttd.telemetry_processor import TelemetryProcessor

    class FailingStore:
        def __init__(self):
            self.closed = False

        async def write_batch(self, batch, *, deadline):
            raise PermanentStorageError()

        async def close(self):
            self.closed = True

    store = FailingStore()
    runtime = _runtime(tmp_path, "normal")
    runner = LiveSimulationRunner(
        _Assets(runtime),
        LiveLaunchPreparation(tmp_path / "runs", lock_root=tmp_path / "locks"),
        expected_identity=_identity(),
        final_result=_fixture_result,
        options=_options(),
        telemetry_factory=lambda run_id: TelemetryProcessor(run_id, store),
    )
    with pytest.raises(SimulationExecutionError) as error:
        runner.run(_config(), run_id=7, artifact_dir=tmp_path / "artifacts")
    assert error.value.failure.code is ExecutionFailureCode.PERSISTENCE_FAILURE
    assert store.closed


@pytest.mark.parametrize(
    "mode",
    ["unpause_no_marker", "unpause_no_new_date", "unpause_same_date", "unpause_older_date"],
)
def test_unpause_requires_exact_marker_and_strictly_newer_date_before_running(
    tmp_path: Path, monkeypatch, mode: str
) -> None:
    commands: list[str] = []
    original_close = PreparedLiveRuntime.close

    def capture_then_close(prepared):
        commands.extend((prepared.workspace / "commands.log").read_text().splitlines())
        return original_close(prepared)

    monkeypatch.setattr(PreparedLiveRuntime, "close", capture_then_close)
    runner, launch = _make_runner(tmp_path, mode, options=_options(startup_timeout_seconds=0.8))
    with pytest.raises(SimulationExecutionError) as error:
        runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")
    assert error.value.failure.code is ExecutionFailureCode.TIMEOUT
    assert commands[0] == "exec scripts/live_unpause_barrier.scr"
    assert not any(command.startswith("exec scripts/live_pause_") for command in commands)
    assert not any(command.startswith("save ") for command in commands)
    assert launch.prepared.lease.closed


@pytest.mark.parametrize("mode", ["unpause_exit", "unpause_close_stdout", "unpause_shutdown"])
def test_unpause_process_or_observer_failure_aborts_before_running(
    tmp_path: Path, monkeypatch, mode: str
) -> None:
    commands: list[str] = []
    original_close = PreparedLiveRuntime.close

    def capture_then_close(prepared):
        commands.extend((prepared.workspace / "commands.log").read_text().splitlines())
        return original_close(prepared)

    monkeypatch.setattr(PreparedLiveRuntime, "close", capture_then_close)
    runner, launch = _make_runner(tmp_path, mode)
    with pytest.raises(SimulationExecutionError):
        runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")
    assert commands[0] == "exec scripts/live_unpause_barrier.scr"
    assert "exec scripts/live_pause_barrier.scr" not in commands
    assert "save final" not in commands
    assert launch.prepared.lease.closed


def test_unpause_marker_waiter_is_armed_before_exact_exec_write(
    tmp_path: Path, monkeypatch
) -> None:
    from app.simulation.openttd.live_launch import UNPAUSE_BARRIER_MARKER
    from app.simulation.openttd.live_runner import _ConsoleProbe

    runner, _ = _make_runner(tmp_path, "normal")
    original_expect = _ConsoleProbe.expect
    original_command = runner._command
    armed = False

    def expect(console, marker):
        nonlocal armed
        if marker == UNPAUSE_BARRIER_MARKER:
            armed = True
        return original_expect(console, marker)

    async def command(process, action, save_name=None, **kwargs):
        if action == "unpause_barrier":
            assert armed
        return await original_command(process, action, save_name, **kwargs)

    monkeypatch.setattr(_ConsoleProbe, "expect", expect)
    monkeypatch.setattr(runner, "_command", command)
    runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")


def test_unpause_marker_is_exact_and_request_scoped() -> None:
    from app.simulation.openttd.live_launch import UNPAUSE_BARRIER_MARKER
    from app.simulation.openttd.live_runner import _ConsoleProbe

    async def exercise() -> None:
        console = _ConsoleProbe()
        console.feed((UNPAUSE_BARRIER_MARKER + "\n").encode())
        seen = console.expect(UNPAUSE_BARRIER_MARKER)
        console.feed(b"noise __LIVE_UNPAUSE_BARRIER_DONE__\n")
        console.feed(b"__LIVE_UNPAUSE_BARRIER_DONE__ suffix\n")
        assert not seen.done()
        console.feed(b"[1950-01-01 00:00:01] __LIVE_UNPAUSE_")
        console.feed(b"BARRIER_DONE__\r\n")
        assert seen.done()
        assert len(console._tail) <= 4096
        next_seen = console.expect(UNPAUSE_BARRIER_MARKER)
        assert not next_seen.done()
        console.clear(UNPAUSE_BARRIER_MARKER, next_seen)

    asyncio.run(exercise())


def test_cancellation_during_unpause_marker_wait_prevents_running(
    tmp_path: Path, monkeypatch
) -> None:
    commands: list[str] = []
    original_close = PreparedLiveRuntime.close

    def capture_then_close(prepared):
        commands.extend((prepared.workspace / "commands.log").read_text().splitlines())
        return original_close(prepared)

    monkeypatch.setattr(PreparedLiveRuntime, "close", capture_then_close)
    runner, launch = _make_runner(tmp_path, "unpause_no_marker")
    cancel = threading.Event()
    unpause_sent = threading.Event()
    runner.cancellation = cancel
    original_command = runner._command
    failures: list[SimulationExecutionError] = []

    async def capture_command(process, action, save_name=None, **kwargs):
        await original_command(process, action, save_name, **kwargs)
        if action == "unpause_barrier":
            unpause_sent.set()

    monkeypatch.setattr(runner, "_command", capture_command)

    def execute() -> None:
        try:
            runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")
        except SimulationExecutionError as error:
            failures.append(error)

    worker = threading.Thread(target=execute)
    worker.start()
    try:
        assert unpause_sent.wait(2)
        cancel.set()
        worker.join(2)
        assert not worker.is_alive()
        assert failures[0].failure.code is ExecutionFailureCode.CANCELLED
        assert "exec scripts/live_pause_barrier.scr" not in commands
        assert launch.prepared.lease.closed
    finally:
        cancel.set()
        worker.join(5)


def test_stdout_reader_failure_during_unpause_aborts_startup(tmp_path: Path, monkeypatch) -> None:
    import app.simulation.openttd.live_runner as module

    original_drain = module._drain
    first_stream = None

    async def selected_drain(stream, probe=None):
        nonlocal first_stream
        if first_stream is None:
            first_stream = stream
        if stream is first_stream:
            while chunk := await stream.read(65536):
                if probe is not None:
                    probe.feed(chunk)
                if b"__LIVE_UNPAUSE_BARRIER_DONE__" in chunk:
                    raise OSError("controlled stdout failure")
            return 0
        return await original_drain(stream, probe)

    monkeypatch.setattr(module, "_drain", selected_drain)
    runner, launch = _make_runner(tmp_path, "normal")
    with pytest.raises(SimulationExecutionError) as error:
        runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")
    assert error.value.failure.code is ExecutionFailureCode.STARTUP_FAILURE
    assert launch.prepared.lease.closed


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


def test_one_stdout_reader_observes_complete_drained_save_command(tmp_path: Path) -> None:
    from app.simulation.openttd.live_runner import _ConsoleProbe, _drain

    runner, launch = _make_runner(tmp_path, "large_output")
    prepared = launch.preparation.prepare(_config(), runner.assets.runtime)

    async def exercise() -> None:
        process = await asyncio.create_subprocess_exec(
            *prepared.argv,
            cwd=prepared.cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        assert process.stdout is not None and process.stderr is not None
        stdout_probe = _ConsoleProbe()
        stdout_drain = asyncio.create_task(_drain(process.stdout, stdout_probe))
        stderr_drain = asyncio.create_task(_drain(process.stderr))
        try:
            started = stdout_probe.expect("Saving map...")
            finished = stdout_probe.expect("Map successfully saved to 'final.sav'.")
            await runner._command(process, "save", "final")
            await asyncio.wait_for(started, 2)
            await asyncio.wait_for(finished, 2)
            assert (prepared.workspace / "commands.log").read_bytes() == b"save final\n"
            await runner._command(process, "quit")
            assert await asyncio.wait_for(process.wait(), 2) == 0
            assert await asyncio.wait_for(stdout_drain, 2) >= 1_000_000
            assert await asyncio.wait_for(stderr_drain, 2) >= 1_000_000
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
            for task in (stdout_drain, stderr_drain):
                if not task.done():
                    task.cancel()
            await asyncio.gather(stdout_drain, stderr_drain, return_exceptions=True)

    try:
        asyncio.run(exercise())
    finally:
        prepared.close()


def test_final_result_failure_cannot_become_success(tmp_path: Path) -> None:
    async def broken(_prepared, _progress, _config):
        raise OSError("private save path and secret")

    runner, launch = _make_runner(tmp_path, "normal", final_result=broken)
    with pytest.raises(SimulationExecutionError) as error:
        runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")
    assert error.value.failure.code is ExecutionFailureCode.FINALIZATION_FAILURE
    assert "private save" not in str(error.value)
    assert launch.prepared.lease.closed


def test_production_runner_uses_real_final_result_operation(tmp_path: Path) -> None:
    from app.simulation.openttd.final_result import FinalResultProcessor
    from app.simulation.openttd.live_runner import LiveSimulationRunner

    runtime = _runtime(tmp_path, "normal")
    launch = LiveLaunchPreparation(tmp_path / "runs", lock_root=tmp_path / "locks")
    runner = LiveSimulationRunner(_Assets(runtime), launch, expected_identity=_identity())
    assert isinstance(runner.final_result, FinalResultProcessor)
    assert not (tmp_path / "runs").exists()


def test_one_owned_controlled_process_finishes_through_public_save_parser(
    tmp_path: Path,
) -> None:
    from app.simulation.openttd.live_runner import LiveSimulationRunner

    runtime = _runtime(tmp_path, "save_valid_fixture")
    config = _config().model_copy(update={"duration_days": 1})
    launch = LiveLaunchPreparation(tmp_path / "runs", lock_root=tmp_path / "locks")
    runner = LiveSimulationRunner(
        _Assets(runtime, config), launch, expected_identity=_identity(), options=_options()
    )
    result = runner.run(config, run_id=1, artifact_dir=tmp_path / "artifacts")
    assert result.simulation_date == date(1950, 1, 2)
    assert result.live_summary is not None
    assert result.live_summary.requested_target_day == date(1950, 1, 1).toordinal() + 365 + 1
    assert result.live_summary.last_observed_day == result.live_summary.requested_target_day
    assert result.live_summary.actual_final_day == 712224
    assert result.live_summary.raw_save_sha256 == (
        "062f7cb99d3fb4fb8ee722191c537331fd0f4e8e6f663b88ac3ab3b9d7ad7fad"
    )
    assert result.raw_artifact_reference is not None
    assert Path(result.raw_artifact_reference).is_file()


@pytest.mark.parametrize(
    "mode",
    [
        "save_no_start",
        "save_no_terminal",
        "save_close_stdout",
        "save_fail",
        "save_wrong_name",
        "save_exit",
        "save_missing",
        "save_directory",
    ],
)
def test_explicit_save_failure_never_returns_success(tmp_path: Path, mode: str) -> None:
    runner, launch = _make_runner(
        tmp_path, mode, options=_options(final_parse_timeout_seconds=0.25)
    )
    with pytest.raises(SimulationExecutionError) as error:
        runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")
    assert error.value.failure.code is ExecutionFailureCode.FINALIZATION_FAILURE
    assert launch.prepared.lease.closed
    assert not launch.prepared.workspace.exists()


def test_save_waiter_rejects_stale_and_wrong_name_without_start() -> None:
    from app.simulation.openttd.live_runner import _ConsoleProbe

    async def exercise() -> None:
        console = _ConsoleProbe()
        console.feed(b"Saving map...\nMap successfully saved to 'final.sav'.\n")
        waiter = console.register_save("final")
        console.feed(b"Map successfully saved to 'final.sav'.\n")
        assert not waiter.started.done()
        console.feed(b"Saving map...\nMap successfully saved to 'old_save.sav'.\n")
        assert waiter.started.done()
        assert not waiter.terminal.done()
        console.feed(b"Map successfully saved to 'final.sav'.\n")
        assert waiter.terminal.result() is True

    asyncio.run(exercise())


def test_dotted_owned_save_basename_is_accepted_consistently() -> None:
    from app.simulation.openttd.live_runner import _ConsoleProbe

    async def exercise() -> None:
        console = _ConsoleProbe()
        waiter = console.register_save("my.final")
        console.feed(b"Saving map...\nMap successfully saved to 'my.final.sav'.\n")
        assert waiter.started.done()
        assert waiter.terminal.result() is True
        console.clear_save(waiter)

    asyncio.run(exercise())


@pytest.mark.parametrize("mode", ["pause_no_marker", "save_no_terminal"])
def test_pause_and_save_share_shutdown_budget_not_parser_budget(tmp_path: Path, mode: str) -> None:
    runner, launch = _make_runner(
        tmp_path,
        mode,
        options=_options(shutdown_timeout_seconds=0.2, final_parse_timeout_seconds=10),
    )
    started = time.monotonic()
    with pytest.raises(SimulationExecutionError) as error:
        runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")
    assert error.value.failure.code is ExecutionFailureCode.FINALIZATION_FAILURE
    assert time.monotonic() - started < 2
    assert launch.prepared.lease.closed


def test_save_waiter_reassembles_chunked_prefixed_crlf_and_utf8_lines() -> None:
    from app.simulation.openttd.live_runner import _ConsoleProbe

    async def exercise() -> None:
        console = _ConsoleProbe()
        waiter = console.register_save("final")
        console.feed("é".encode()[:1])
        console.feed("é".encode()[1:] + b" ordinary noise\n[1950-01-01 00:00:00] Saving ")
        assert not waiter.started.done()
        console.feed(b"map...\r\nnoise\nMap successfully saved to 'old.sav'.\n")
        assert waiter.started.done()
        assert not waiter.terminal.done()
        console.feed(b"[1950-01-01 00:00:01] Map successfully saved to 'fin")
        console.feed(b"al.sav'.\r\n")
        assert waiter.terminal.result() is True
        console.clear_save(waiter)
        next_waiter = console.register_save("final")
        assert not next_waiter.started.done()
        assert not next_waiter.terminal.done()
        console.clear_save(next_waiter)

    asyncio.run(exercise())


def test_marker_bearing_ordinary_noise_cannot_satisfy_save_waiter() -> None:
    from app.simulation.openttd.live_runner import _ConsoleProbe

    async def exercise() -> None:
        console = _ConsoleProbe()
        waiter = console.register_save("final")
        console.feed(b"AI log Saving map...\n")
        assert not waiter.started.done()
        console.feed(b"Saving map...\nAI log Map successfully saved to 'final.sav'.\n")
        assert waiter.started.done()
        assert not waiter.terminal.done()
        console.feed(b"Map successfully saved to 'final.sav'.\n")
        assert waiter.terminal.result() is True

    asyncio.run(exercise())


def test_bounded_probe_notifies_active_save_without_storing_noisy_history() -> None:
    from app.simulation.openttd.live_runner import _ConsoleProbe

    async def exercise() -> None:
        console = _ConsoleProbe()
        waiter = console.register_save("final")
        console.feed(b"ordinary output without newline" * 10_000)
        assert len(console._tail) <= 4096
        console.feed(b"\n" + b"ordinary line\n" * 10_000 + b"Saving map...\n")
        assert waiter.started.done()
        assert len(console._tail) <= 4096
        assert len(console._pending) == 0
        console.feed(b"ordinary line\n" * 10_000)
        console.feed(b"Map successfully saved to 'final.sav'.\n")
        assert waiter.terminal.result() is True

    asyncio.run(exercise())


def test_closed_stdout_interrupts_save_wait_before_deadline(tmp_path: Path) -> None:
    runner, launch = _make_runner(
        tmp_path,
        "save_close_stdout",
        options=_options(final_parse_timeout_seconds=3),
    )
    started = time.monotonic()
    with pytest.raises(SimulationExecutionError) as error:
        runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")
    assert error.value.failure.code is ExecutionFailureCode.FINALIZATION_FAILURE
    assert time.monotonic() - started < 2
    assert launch.prepared.lease.closed


def test_failed_stdout_drain_interrupts_save_wait(tmp_path: Path, monkeypatch) -> None:
    import app.simulation.openttd.live_runner as module

    original_drain = module._drain

    async def failing_stdout_drain(stream, probe=None):
        assert probe is not None
        while chunk := await stream.read(65536):
            probe.feed(chunk)
            if probe._save is not None and probe._save.started.done():
                raise OSError("controlled stdout reader failure")
        return 0

    # The stdout reader is created first; stderr retains its own normal reader.
    first_stream = None

    async def selected_drain(stream, probe=None):
        nonlocal first_stream
        if first_stream is None:
            first_stream = stream
        if stream is first_stream:
            return await failing_stdout_drain(stream, probe)
        return await original_drain(stream, probe)

    monkeypatch.setattr(module, "_drain", selected_drain)
    runner, launch = _make_runner(
        tmp_path, "save_no_terminal", options=_options(final_parse_timeout_seconds=3)
    )
    started = time.monotonic()
    with pytest.raises(SimulationExecutionError) as error:
        runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")
    assert error.value.failure.code is ExecutionFailureCode.FINALIZATION_FAILURE
    assert time.monotonic() - started < 2
    assert launch.prepared.lease.closed


def test_save_waiter_is_registered_before_save_bytes_are_written(
    tmp_path: Path, monkeypatch
) -> None:
    from app.simulation.openttd.live_runner import _ConsoleProbe

    registered = False
    original_register = _ConsoleProbe.register_save

    def register(console, basename):
        nonlocal registered
        registered = True
        return original_register(console, basename)

    monkeypatch.setattr(_ConsoleProbe, "register_save", register)
    runner, _ = _make_runner(tmp_path, "normal")
    original_command = runner._command

    async def check_command(process, action, save_name=None, **kwargs):
        if action == "save":
            assert registered
        return await original_command(process, action, save_name, **kwargs)

    monkeypatch.setattr(runner, "_command", check_command)
    runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")


def test_cancellation_while_waiting_for_save_ack_reaps_child(tmp_path: Path, monkeypatch) -> None:
    runner, launch = _make_runner(
        tmp_path,
        "save_no_terminal",
        options=_options(final_parse_timeout_seconds=3),
    )
    cancel = threading.Event()
    save_sent = threading.Event()
    runner.cancellation = cancel
    original_command = runner._command
    errors: list[SimulationExecutionError] = []

    async def capture_command(process, action, save_name=None, **kwargs):
        await original_command(process, action, save_name, **kwargs)
        if action == "save":
            save_sent.set()

    monkeypatch.setattr(runner, "_command", capture_command)

    def execute() -> None:
        try:
            runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")
        except SimulationExecutionError as error:
            errors.append(error)

    worker = threading.Thread(target=execute)
    worker.start()
    try:
        assert save_sent.wait(2)
        cancel.set()
        worker.join(2)
        assert not worker.is_alive()
        assert errors[0].failure.code is ExecutionFailureCode.CANCELLED
        assert launch.prepared.lease.closed
    finally:
        cancel.set()
        worker.join(5)


def test_noisy_stdio_selected_child_receives_pause_then_save_without_losing_ack(
    tmp_path: Path, monkeypatch
) -> None:
    commands: list[str] = []
    original_close = PreparedLiveRuntime.close

    def capture_then_close(prepared):
        commands.extend((prepared.workspace / "commands.log").read_text().splitlines(keepends=True))
        return original_close(prepared)

    monkeypatch.setattr(PreparedLiveRuntime, "close", capture_then_close)
    runner, launch = _make_runner(
        tmp_path,
        "noisy_stdio_select",
        options=_options(final_parse_timeout_seconds=3),
    )
    result = runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")
    assert result.live_summary is not None
    assert commands == [
        "exec scripts/live_unpause_barrier.scr\n",
        "exec scripts/live_pause_barrier.scr\n",
        "save final\n",
        "quit\n",
    ]
    assert launch.prepared.lease.closed


def test_pause_marker_is_request_scoped_exact_and_reassembles_noisy_chunks() -> None:
    from app.simulation.openttd.live_launch import PAUSE_BARRIER_MARKER
    from app.simulation.openttd.live_runner import _ConsoleProbe

    async def exercise() -> None:
        console = _ConsoleProbe()
        console.feed((PAUSE_BARRIER_MARKER + "\n").encode())  # stale marker
        seen = console.expect(PAUSE_BARRIER_MARKER)
        console.feed(b"other __LIVE_PAUSE_BARRIER_DONE__\n")
        console.feed(b"__LIVE_PAUSE_BARRIER_DONE__ suffix\n")
        console.feed(b"ordinary line\n" * 30_000)
        assert not seen.done()
        console.feed(b"[1950-01-01 00:00:01] __LIVE_PAUSE_")
        console.feed(b"BARRIER_DONE__\r\n")
        assert seen.done()
        assert len(console._tail) <= 4096
        assert not console._pending
        next_seen = console.expect(PAUSE_BARRIER_MARKER)
        assert not next_seen.done()
        console.clear(PAUSE_BARRIER_MARKER, next_seen)

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "mode",
    ["pause_no_marker", "pause_exit", "pause_close_stdout", "pause_shutdown"],
)
def test_pause_barrier_failure_never_sends_save(tmp_path: Path, monkeypatch, mode: str) -> None:
    commands: list[str] = []
    original_close = PreparedLiveRuntime.close

    def capture_then_close(prepared):
        commands.extend((prepared.workspace / "commands.log").read_text().splitlines())
        return original_close(prepared)

    monkeypatch.setattr(PreparedLiveRuntime, "close", capture_then_close)
    runner, launch = _make_runner(tmp_path, mode, options=_options(final_parse_timeout_seconds=0.3))
    with pytest.raises(SimulationExecutionError):
        runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")
    assert "exec scripts/live_pause_barrier.scr" in commands
    assert not any(command.startswith("save ") for command in commands)
    assert launch.prepared.lease.closed


def test_pause_waiter_armed_before_exact_exec_command_and_save_after_marker(
    tmp_path: Path, monkeypatch
) -> None:
    from app.simulation.openttd.live_launch import PAUSE_BARRIER_MARKER
    from app.simulation.openttd.live_runner import _ConsoleProbe

    runner, _ = _make_runner(tmp_path, "normal")
    original_expect = _ConsoleProbe.expect
    original_command = runner._command
    armed = False

    def expect(console, marker):
        nonlocal armed
        if marker == PAUSE_BARRIER_MARKER:
            armed = True
        return original_expect(console, marker)

    async def command(process, action, save_name=None, **kwargs):
        if action == "pause_barrier":
            assert armed
        if action == "save":
            assert armed
        return await original_command(process, action, save_name, **kwargs)

    monkeypatch.setattr(_ConsoleProbe, "expect", expect)
    monkeypatch.setattr(runner, "_command", command)
    runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")


def test_arbitrary_exec_cannot_be_sent_through_lifecycle_command(tmp_path: Path) -> None:
    from app.simulation.openttd.live_runner import _RunFailure

    runner, _ = _make_runner(tmp_path, "normal")

    class ClosedProcess:
        stdin = None

    async def exercise() -> None:
        with pytest.raises(_RunFailure):
            await runner._command(ClosedProcess(), "exec scripts/other.scr")

    asyncio.run(exercise())


def test_cancellation_during_pause_barrier_reaps_child_without_saving(
    tmp_path: Path, monkeypatch
) -> None:
    commands: list[str] = []
    original_close = PreparedLiveRuntime.close

    def capture_then_close(prepared):
        commands.extend((prepared.workspace / "commands.log").read_text().splitlines())
        return original_close(prepared)

    monkeypatch.setattr(PreparedLiveRuntime, "close", capture_then_close)
    runner, launch = _make_runner(
        tmp_path, "pause_no_marker", options=_options(final_parse_timeout_seconds=3)
    )
    cancel = threading.Event()
    barrier_sent = threading.Event()
    runner.cancellation = cancel
    original_command = runner._command
    failures: list[SimulationExecutionError] = []

    async def capture_command(process, action, save_name=None, **kwargs):
        await original_command(process, action, save_name, **kwargs)
        if action == "pause_barrier":
            barrier_sent.set()

    monkeypatch.setattr(runner, "_command", capture_command)

    def execute() -> None:
        try:
            runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")
        except SimulationExecutionError as error:
            failures.append(error)

    worker = threading.Thread(target=execute)
    worker.start()
    try:
        assert barrier_sent.wait(2)
        cancel.set()
        worker.join(2)
        assert not worker.is_alive()
        assert failures[0].failure.code is ExecutionFailureCode.CANCELLED
        assert "save final" not in commands
        assert launch.prepared.lease.closed
    finally:
        cancel.set()
        worker.join(5)


def test_stdout_reader_failure_aborts_pause_barrier(tmp_path: Path, monkeypatch) -> None:
    import app.simulation.openttd.live_runner as module

    original_drain = module._drain
    first_stream = None

    async def selected_drain(stream, probe=None):
        nonlocal first_stream
        if first_stream is None:
            first_stream = stream
        if stream is first_stream:
            while chunk := await stream.read(65536):
                if probe is not None:
                    probe.feed(chunk)
                if b"__LIVE_PAUSE_BARRIER_DONE__" in chunk:
                    raise OSError("controlled stdout failure")
            return 0
        return await original_drain(stream, probe)

    monkeypatch.setattr(module, "_drain", selected_drain)
    runner, launch = _make_runner(tmp_path, "normal")
    with pytest.raises(SimulationExecutionError) as error:
        runner.run(_config(), run_id=1, artifact_dir=tmp_path / "artifacts")
    assert error.value.failure.code is ExecutionFailureCode.FINALIZATION_FAILURE
    assert launch.prepared.lease.closed


def test_controlled_console_diagnostic_sequential_echo_exec_and_missing_script(
    tmp_path: Path,
) -> None:
    """A drained stdin write is distinct from an observed console execution."""
    from app.simulation.openttd.live_runner import _ConsoleProbe, _drain

    runner, launch = _make_runner(tmp_path, "normal")
    prepared = launch.preparation.prepare(_config(), runner.assets.runtime)
    script = prepared.workspace / "scripts/t09_exec_probe.scr"
    script.write_bytes(b"echo __T09_EXEC_PROBE__\n")

    async def exercise() -> None:
        process = await asyncio.create_subprocess_exec(
            *prepared.argv,
            cwd=prepared.cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        assert process.stdin is not None and process.stdout is not None
        assert process.stderr is not None
        probe = _ConsoleProbe()
        stdout_drain = asyncio.create_task(_drain(process.stdout, probe))
        stderr_drain = asyncio.create_task(_drain(process.stderr))

        async def issue(command: bytes, marker: str) -> None:
            seen = probe.expect(marker)
            process.stdin.write(command)
            await process.stdin.drain()
            await asyncio.wait_for(seen, 2)
            probe.clear(marker, seen)

        try:
            await issue(b"echo __T09_DIRECT_STDIN_PROBE__\n", "__T09_DIRECT_STDIN_PROBE__")
            await issue(b"exec scripts/t09_exec_probe.scr\n", "__T09_EXEC_PROBE__")
            await issue(
                b"exec scripts/t09_missing.scr\n",
                "Script file 'scripts/t09_missing.scr' not found.",
            )
            assert (prepared.workspace / "commands.log").read_bytes() == (
                b"echo __T09_DIRECT_STDIN_PROBE__\n"
                b"exec scripts/t09_exec_probe.scr\n"
                b"exec scripts/t09_missing.scr\n"
            )
            assert not stdout_drain.done()
            process.stdin.write(b"quit\n")
            await process.stdin.drain()
            await asyncio.wait_for(process.wait(), 2)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
            await asyncio.gather(stdout_drain, stderr_drain, return_exceptions=True)

    try:
        asyncio.run(exercise())
    finally:
        prepared.close()


def test_select_plus_buffered_line_input_can_strand_coalesced_save(tmp_path: Path) -> None:
    from app.simulation.openttd.live_runner import _ConsoleProbe, _drain

    runner, launch = _make_runner(tmp_path, "stdio_read_ahead_probe")
    prepared = launch.preparation.prepare(_config(), runner.assets.runtime)

    async def exercise() -> None:
        process = await asyncio.create_subprocess_exec(
            *prepared.argv,
            cwd=prepared.cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        assert process.stdin is not None and process.stdout is not None
        assert process.stderr is not None
        stdout_probe = _ConsoleProbe()
        stderr_probe = _ConsoleProbe()
        stdout_drain = asyncio.create_task(_drain(process.stdout, stdout_probe))
        stderr_drain = asyncio.create_task(_drain(process.stderr, stderr_probe))
        try:
            kernel_empty = stderr_probe.expect("fd-empty-after-pause")
            waiter = stdout_probe.register_save("final")
            process.stdin.write(b"pause\nsave final\n")
            await process.stdin.drain()
            await asyncio.wait_for(kernel_empty, 2)
            assert (prepared.workspace / "commands.log").read_bytes() == b"pause\n"
            process.stdin.write(b"echo wake\n")
            await process.stdin.drain()
            await asyncio.wait_for(waiter.started, 2)
            await asyncio.wait_for(waiter.terminal, 2)
            assert waiter.terminal.result() is True
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
            for task in (stdout_drain, stderr_drain):
                if not task.done():
                    task.cancel()
            await asyncio.gather(stdout_drain, stderr_drain, return_exceptions=True)

    try:
        asyncio.run(exercise())
    finally:
        prepared.close()


def test_raw_unpause_then_exec_can_strand_script_until_another_stdin_write(
    tmp_path: Path,
) -> None:
    from app.simulation.openttd.live_launch import PAUSE_BARRIER_MARKER
    from app.simulation.openttd.live_runner import _ConsoleProbe, _drain

    runner, launch = _make_runner(tmp_path, "stdio_read_ahead_probe")
    prepared = launch.preparation.prepare(_config(), runner.assets.runtime)

    async def exercise() -> None:
        process = await asyncio.create_subprocess_exec(
            *prepared.argv,
            cwd=prepared.cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        assert process.stdin is not None and process.stdout is not None
        assert process.stderr is not None
        stdout_probe = _ConsoleProbe()
        stderr_probe = _ConsoleProbe()
        stdout_drain = asyncio.create_task(_drain(process.stdout, stdout_probe))
        stderr_drain = asyncio.create_task(_drain(process.stderr, stderr_probe))
        try:
            kernel_empty = stderr_probe.expect("fd-empty-after-pause")
            marker = stdout_probe.expect(PAUSE_BARRIER_MARKER)
            process.stdin.write(b"unpause\nexec scripts/live_pause_barrier.scr\n")
            await process.stdin.drain()
            await asyncio.wait_for(kernel_empty, 2)
            assert (prepared.workspace / "commands.log").read_bytes() == b"unpause\n"
            assert not marker.done()
            process.stdin.write(b"echo wake\n")
            await process.stdin.drain()
            await asyncio.wait_for(marker, 2)
            assert (
                (prepared.workspace / "commands.log")
                .read_bytes()
                .startswith(b"unpause\nexec scripts/live_pause_barrier.scr\n")
            )
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
            for task in (stdout_drain, stderr_drain):
                if not task.done():
                    task.cancel()
            await asyncio.gather(stdout_drain, stderr_drain, return_exceptions=True)

    try:
        asyncio.run(exercise())
    finally:
        prepared.close()


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

    async def stalled(_prepared, _progress, _config):
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
    async def stalled(_prepared, _progress, _config):
        await asyncio.Event().wait()

    runner, launch = _make_runner(
        tmp_path,
        "save_shutdown",
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
