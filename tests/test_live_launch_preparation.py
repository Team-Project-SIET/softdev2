"""Per-run launch resources are prepared without starting a game or observer."""

import configparser
import multiprocessing
import shutil
import socket
import stat
import time
import traceback
from dataclasses import replace
from pathlib import Path

import pytest

from app.experiments.domain import ExperimentConfig, ScenarioConfig
from app.experiments.strategies import (
    BaselineStrategy,
    SimpleMultimodalStrategy,
    SimpleRoadOnlyStrategy,
)
from app.simulation.openttd.runtime_assets import PreparedRuntime


def _config(strategy=None, scenario_text="[game_creation]\nmap_x = 8\nmap_y = 8\n"):
    scenario = ScenarioConfig(identifier="map", version="1", openttd_config=scenario_text)
    planning, ai = (strategy or SimpleRoadOnlyStrategy()).configure(scenario)
    return ExperimentConfig(
        scenario=scenario,
        planning=planning,
        ai=ai,
        openttd_version="13.4",
        opengfx_version="7.1",
        seed=17,
        duration_days=30,
    )


@pytest.fixture
def runtime(tmp_path: Path) -> PreparedRuntime:
    cache = tmp_path / "cache"
    cache.mkdir()
    executable = cache / "openttd"
    graphics = cache / "opengfx-7.1.tar"
    ai = cache / "SimpleAI-14.tar"
    dependencies = tuple(cache / f"library-{i}.tar" for i in range(5))
    for path in (executable, graphics, ai, *dependencies):
        path.write_bytes(b"pinned")
    return PreparedRuntime(
        executable_path=executable,
        opengfx_archive_path=graphics,
        ai_archive_path=ai,
        dependency_archive_paths=dependencies,
        ai_configuration=_config().ai,
        provenance={"cache_identity": "openttd-13.4-pinned-v1", "assets": ()},
    )


def test_expired_startup_deadline_creates_no_launch_resources(
    tmp_path: Path, runtime: PreparedRuntime
) -> None:
    from app.simulation.openttd.live_launch import (
        LiveLaunchCode,
        LiveLaunchError,
        LiveLaunchPreparation,
    )

    preparer = LiveLaunchPreparation(tmp_path / "runs", lock_root=tmp_path / "locks")
    with pytest.raises(LiveLaunchError) as error:
        preparer.prepare(_config(), runtime, deadline=time.monotonic() - 1)
    assert error.value.code is LiveLaunchCode.DEADLINE_EXCEEDED
    assert not (tmp_path / "runs").exists()
    assert not (tmp_path / "locks").exists()


def test_prepares_private_versioned_workspace_and_fresh_secret(
    tmp_path: Path, runtime: PreparedRuntime, monkeypatch
) -> None:
    from app.simulation.openttd.live_launch import LiveLaunchPreparation

    def reject_process(*_args, **_kwargs):
        raise AssertionError("T06 must not launch OpenTTD")

    def reject_connection(*_args, **_kwargs):
        raise AssertionError("T06 must not connect to Admin Network")

    monkeypatch.setattr("subprocess.Popen", reject_process)
    monkeypatch.setattr(socket.socket, "connect", reject_connection)
    preparer = LiveLaunchPreparation(tmp_path / "runs", lock_root=tmp_path / "locks")
    config = _config()
    scenario_identity = config.scenario.model_dump()
    strategy_identity = config.planning.model_dump()
    first = preparer.prepare(config, runtime)
    second = preparer.prepare(config, runtime)
    try:
        assert first.workspace != second.workspace
        assert stat.S_IMODE(first.workspace.stat().st_mode) == 0o700
        assert stat.S_IMODE(first.secrets_config_path.stat().st_mode) == 0o600
        assert first.admin_password != second.admin_password
        assert 0 < len(first.admin_password.encode("utf-8")) <= 32
        assert first.admin_password in first.secrets_config_path.read_text()
        assert first.admin_password not in repr(first.argv)
        assert first.admin_password not in repr(first.provenance)
        assert first.admin_password not in repr(first)
        assert first.admin_password not in first.main_config_path.read_text()
        assert first.admin_password not in first.private_config_path.read_text()
        assert first.game_port != first.admin_port
        assert 39770 <= first.game_port <= 39999
        assert 39770 <= first.admin_port <= 39999
        assert first.argv[0] == str(runtime.executable_path)
        assert first.cwd == first.workspace
        assert first.runtime is runtime
        assert first.provenance["runtime"] == runtime.provenance
        assert first.provenance["execution_mode"] == "live"
        assert first.provenance["config_schema"] == "openttd-13.4-ini-v2"
        assert config.scenario.model_dump() == scenario_identity
        assert config.planning.model_dump() == strategy_identity
        main = configparser.ConfigParser()
        main.read(first.main_config_path)
        assert main["version"]["ini_version"] == "2"
        assert main["network"]["server_game_type"] == "local"
        assert main["network"]["min_active_clients"] == "0"
        assert main["gui"]["autosave"] == "monthly"
        assert main["gui"]["pause_on_newgame"] == "true"
        assert main["gui"]["threaded_saves"] == "false"
        assert main["gui"]["keep_all_autosave"] == "true"
        assert main["network"]["restart_game_year"] == "0"
        assert main["network"]["reload_cfg"] == "false"
        assert main["ai"]["ai_in_multiplayer"] == "true"
        assert first.private_config_path.read_text() == "[server_bind_addresses]\n127.0.0.1\n"
        assert main["ai_players"]["SimpleAI"] == "use_aircraft=0,use_roadvehs=1,use_trains=0"
        assert not (runtime.executable_path.parent / "save").exists()
        assert first.final_save_path.parent == first.workspace / "save"
        assert first.graphics_archive_path.parent == first.workspace / "baseset"
        assert all(path.is_relative_to(first.workspace) for path in first.dependency_archive_paths)
    finally:
        first.close()
        second.close()
    assert not first.workspace.exists()
    assert not second.workspace.exists()


def test_fixed_port_collision_and_release(tmp_path: Path, runtime: PreparedRuntime) -> None:
    from app.simulation.openttd.live_launch import LiveLaunchError, LiveLaunchPreparation

    preparer = LiveLaunchPreparation(tmp_path / "runs", lock_root=tmp_path / "locks")
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        port = occupied.getsockname()[1]
        with pytest.raises(LiveLaunchError):
            preparer.prepare(_config(), runtime, game_port=port, admin_port=port + 1)
    first = preparer.prepare(_config(), runtime, game_port=port, admin_port=port + 1)
    try:
        with pytest.raises(LiveLaunchError):
            preparer.prepare(_config(), runtime, game_port=port, admin_port=port + 1)
    finally:
        first.close()
    second = preparer.prepare(_config(), runtime, game_port=port, admin_port=port + 1)
    second.close()


@pytest.mark.parametrize(
    ("strategy", "expected"),
    [
        (BaselineStrategy(), "trAIns ="),
        (SimpleRoadOnlyStrategy(), "SimpleAI = use_aircraft=0,use_roadvehs=1,use_trains=0"),
        (SimpleMultimodalStrategy(), "SimpleAI = use_aircraft=1,use_roadvehs=1,use_trains=1"),
    ],
)
def test_existing_ai_startup_parameters_are_preserved(
    tmp_path: Path, runtime: PreparedRuntime, strategy, expected: str
) -> None:
    from app.simulation.openttd.live_launch import LiveLaunchPreparation

    config = _config(strategy)
    runtime = replace(runtime, ai_configuration=config.ai)
    prepared = LiveLaunchPreparation(tmp_path / "runs", lock_root=tmp_path / "locks").prepare(
        config, runtime
    )
    try:
        assert expected in prepared.main_config_path.read_text()
        assert prepared.provenance["ai_parameters"] == dict(config.ai.parameters)
        assert prepared.ai_archive_path.read_bytes() == b"pinned"
        assert len(prepared.dependency_archive_paths) == 5
    finally:
        prepared.close()


@pytest.mark.parametrize("protocol", ["game_udp", "admin_tcp"])
def test_occupied_udp_or_admin_endpoint_is_rejected(
    tmp_path: Path, runtime: PreparedRuntime, protocol: str
) -> None:
    from app.simulation.openttd.live_launch import (
        LiveLaunchCode,
        LiveLaunchError,
        LiveLaunchPreparation,
    )

    kind = socket.SOCK_DGRAM if protocol == "game_udp" else socket.SOCK_STREAM
    with socket.socket(socket.AF_INET, kind) as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied_port = occupied.getsockname()[1]
        game = occupied_port if protocol == "game_udp" else occupied_port + 1
        admin = occupied_port + 1 if protocol == "game_udp" else occupied_port
        preparer = LiveLaunchPreparation(tmp_path / "runs", lock_root=tmp_path / "locks")
        with pytest.raises(LiveLaunchError) as error:
            preparer.prepare(_config(), runtime, game_port=game, admin_port=admin)
        assert error.value.code is LiveLaunchCode.PORT_IN_USE
        assert occupied.getsockname()[1] == occupied_port


@pytest.mark.parametrize("invalid", [0, 65536, True])
def test_invalid_fixed_ports_fail_before_workspace_creation(
    tmp_path: Path, runtime: PreparedRuntime, invalid
) -> None:
    from app.simulation.openttd.live_launch import (
        LiveLaunchCode,
        LiveLaunchError,
        LiveLaunchPreparation,
    )

    preparer = LiveLaunchPreparation(tmp_path / "runs", lock_root=tmp_path / "locks")
    with pytest.raises(LiveLaunchError) as error:
        preparer.prepare(_config(), runtime, game_port=invalid, admin_port=39771)
    assert error.value.code is LiveLaunchCode.INVALID_PORT
    assert not (tmp_path / "runs").exists()


@pytest.mark.parametrize("save_name", ["../escape.sav", "/tmp/escape.sav", "a/other.sav", "..sav"])
def test_unsafe_save_paths_are_rejected_before_workspace_creation(
    tmp_path: Path, runtime: PreparedRuntime, save_name: str
) -> None:
    from app.simulation.openttd.live_launch import (
        LiveLaunchCode,
        LiveLaunchError,
        LiveLaunchPreparation,
    )

    with pytest.raises(LiveLaunchError) as error:
        LiveLaunchPreparation(tmp_path / "runs", lock_root=tmp_path / "locks").prepare(
            _config(), runtime, save_name=save_name
        )
    assert error.value.code is LiveLaunchCode.UNSAFE_PATH
    assert not (tmp_path / "runs").exists()


@pytest.mark.parametrize(
    ("scenario_text", "code"),
    [
        ("[network]\nserver_game_type = public\n", "conflicting_owned_setting"),
        ("[gui]\nautosave = off\n", "conflicting_owned_setting"),
        ("[game_creation]\nmap_x = nope\n", "invalid_configuration"),
        ("[game_creation]\nmap_x = 13\n", "invalid_configuration"),
        ("[game_creation]\nmap_y = 5\n", "invalid_configuration"),
        ("[game_creation]\nstarting_year = 0\n", "invalid_configuration"),
        ("[game_creation]\nstarting_year = 10000\n", "invalid_configuration"),
        ("[game_creation]\nstarting_year = 5000001\n", "invalid_configuration"),
        ("[version]\nini_version = 0\n", "conflicting_owned_setting"),
        ("[DEFAULT]\nserver_port = 1234\n", "invalid_configuration"),
    ],
)
def test_owned_and_invalid_scenario_settings_are_rejected(
    tmp_path: Path, runtime: PreparedRuntime, scenario_text: str, code: str
) -> None:
    from app.simulation.openttd.live_launch import LiveLaunchError, LiveLaunchPreparation

    with pytest.raises(LiveLaunchError) as error:
        LiveLaunchPreparation(tmp_path / "runs", lock_root=tmp_path / "locks").prepare(
            _config(scenario_text=scenario_text), runtime
        )
    assert error.value.code.value == code


def test_failed_secret_write_removes_only_created_workspace_and_releases_lease(
    tmp_path: Path, runtime: PreparedRuntime, monkeypatch
) -> None:
    import app.simulation.openttd.live_launch as module

    root = tmp_path / "runs"
    root.mkdir()
    unrelated = root / "unrelated.txt"
    unrelated.write_text("keep")
    original = module._write_owned
    leaked: list[str] = []

    def fail_secret(path: Path, content: str) -> None:
        if path.name == "secrets.cfg":
            leaked.append(content.split("admin_password = ", 1)[1].strip())
            failure_message = content + "private path must not escape"
            raise OSError(failure_message)
        original(path, content)

    monkeypatch.setattr(module, "_write_owned", fail_secret)
    preparer = module.LiveLaunchPreparation(root, lock_root=tmp_path / "locks")
    with pytest.raises(module.LiveLaunchError) as error:
        preparer.prepare(_config(), runtime, game_port=39770, admin_port=39771)
    assert error.value.code is module.LiveLaunchCode.SECRET_FAILURE
    assert "private path" not in str(error.value)
    formatted = "".join(traceback.format_exception(error.value))
    assert "private path" not in formatted
    assert leaked[0] not in formatted
    assert list(root.iterdir()) == [unrelated]
    assert unrelated.read_text() == "keep"
    monkeypatch.undo()
    prepared = preparer.prepare(_config(), runtime, game_port=39770, admin_port=39771)
    prepared.close()


def _hold_ports(root: str, lock_root: str, runtime: PreparedRuntime, ready, release) -> None:
    from app.simulation.openttd.live_launch import LiveLaunchPreparation

    prepared = LiveLaunchPreparation(Path(root), lock_root=Path(lock_root)).prepare(
        _config(), runtime, game_port=39770, admin_port=39771
    )
    ready.put(True)
    release.wait()
    prepared.close()


def test_independent_processes_cannot_hold_same_advisory_lease(
    tmp_path: Path, runtime: PreparedRuntime
) -> None:
    from app.simulation.openttd.live_launch import (
        LiveLaunchCode,
        LiveLaunchError,
        LiveLaunchPreparation,
    )

    context = multiprocessing.get_context("fork")
    ready = context.Queue()
    release = context.Event()
    process = context.Process(
        target=_hold_ports,
        args=(str(tmp_path / "runs"), str(tmp_path / "locks"), runtime, ready, release),
    )
    try:
        process.start()
        assert ready.get(timeout=5) is True
        with pytest.raises(LiveLaunchError) as error:
            LiveLaunchPreparation(tmp_path / "runs", lock_root=tmp_path / "locks").prepare(
                _config(), runtime, game_port=39770, admin_port=39771
            )
        assert error.value.code is LiveLaunchCode.LEASE_CONFLICT
    finally:
        release.set()
        process.join(timeout=5)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
    assert process.exitcode == 0


def test_configurable_range_selects_distinct_ports_and_keeps_logical_lease(
    tmp_path: Path, runtime: PreparedRuntime
) -> None:
    from app.simulation.openttd.live_launch import LiveLaunchPreparation

    preparer = LiveLaunchPreparation(
        tmp_path / "runs", lock_root=tmp_path / "locks", port_range=(39880, 39883)
    )
    first = preparer.prepare(_config(), runtime)
    second = preparer.prepare(_config(), runtime)
    try:
        assert {first.game_port, first.admin_port} == {39880, 39881}
        assert {second.game_port, second.admin_port} == {39882, 39883}
        assert not first.lease.closed
        # Temporary bind-check sockets are gone; only advisory ownership remains.
        with socket.socket() as external:
            external.bind(("127.0.0.1", first.game_port))
    finally:
        first.close()
        second.close()
    assert first.lease.closed and second.lease.closed


def test_lock_directory_permission_failure_is_sanitized(
    tmp_path: Path, runtime: PreparedRuntime
) -> None:
    from app.simulation.openttd.live_launch import (
        LiveLaunchCode,
        LiveLaunchError,
        LiveLaunchPreparation,
    )

    locks = tmp_path / "locks"
    locks.mkdir(mode=0o755)
    with pytest.raises(LiveLaunchError) as error:
        LiveLaunchPreparation(tmp_path / "runs", lock_root=locks).prepare(_config(), runtime)
    assert error.value.code is LiveLaunchCode.PERMISSION_FAILURE
    assert str(tmp_path) not in str(error.value)
    assert not (tmp_path / "runs").exists()


def test_workspace_creation_failure_releases_lease_without_deleting_user_file(
    tmp_path: Path, runtime: PreparedRuntime
) -> None:
    from app.simulation.openttd.live_launch import (
        LiveLaunchCode,
        LiveLaunchError,
        LiveLaunchPreparation,
    )

    root = tmp_path / "runs"
    root.write_text("user content")
    preparer = LiveLaunchPreparation(root, lock_root=tmp_path / "locks")
    with pytest.raises(LiveLaunchError) as error:
        preparer.prepare(_config(), runtime, game_port=39770, admin_port=39771)
    assert error.value.code is LiveLaunchCode.WORKSPACE_FAILURE
    assert root.read_text() == "user content"
    root.unlink()
    prepared = preparer.prepare(_config(), runtime, game_port=39770, admin_port=39771)
    prepared.close()


@pytest.mark.parametrize("field", ["openttd_version", "opengfx_version"])
def test_mismatched_runtime_version_is_rejected_before_resource_allocation(
    tmp_path: Path, runtime: PreparedRuntime, field: str
) -> None:
    from app.simulation.openttd.live_launch import (
        LiveLaunchCode,
        LiveLaunchError,
        LiveLaunchPreparation,
    )

    config = _config().model_copy(update={field: "14.0"})
    with pytest.raises(LiveLaunchError) as error:
        LiveLaunchPreparation(tmp_path / "runs", lock_root=tmp_path / "locks").prepare(
            config, runtime
        )
    assert error.value.code is LiveLaunchCode.INVALID_CONFIGURATION
    assert not (tmp_path / "runs").exists()


def test_unapproved_strategy_identity_cannot_enter_launch_provenance(
    tmp_path: Path, runtime: PreparedRuntime
) -> None:
    from app.simulation.openttd.live_launch import (
        LiveLaunchCode,
        LiveLaunchError,
        LiveLaunchPreparation,
    )

    planning = _config().planning.model_copy(update={"strategy_identifier": "raw-user-value"})
    config = _config().model_copy(update={"planning": planning})
    with pytest.raises(LiveLaunchError) as error:
        LiveLaunchPreparation(tmp_path / "runs", lock_root=tmp_path / "locks").prepare(
            config, runtime
        )
    assert error.value.code is LiveLaunchCode.INVALID_CONFIGURATION
    assert not (tmp_path / "runs").exists()


def test_incomplete_preparation_cleanup_has_a_typed_failure(
    tmp_path: Path, runtime: PreparedRuntime, monkeypatch
) -> None:
    import app.simulation.openttd.live_launch as module

    root = tmp_path / "runs"
    preparer = module.LiveLaunchPreparation(root, lock_root=tmp_path / "locks")
    original_write = module._write_owned

    def fail_write(path: Path, content: str) -> None:
        if path.name == "secrets.cfg":
            raise OSError("private credential must not escape")
        original_write(path, content)

    def fail_remove(_path: Path) -> None:
        raise OSError("private cleanup path must not escape")

    monkeypatch.setattr(module, "_write_owned", fail_write)
    monkeypatch.setattr(module.shutil, "rmtree", fail_remove)
    with pytest.raises(module.LiveLaunchError) as error:
        preparer.prepare(_config(), runtime, game_port=39770, admin_port=39771)
    assert error.value.code is module.LiveLaunchCode.CLEANUP_FAILURE
    assert "private" not in "".join(traceback.format_exception(error.value))
    monkeypatch.undo()
    for workspace in root.glob("live-*"):
        shutil.rmtree(workspace)
    prepared = preparer.prepare(_config(), runtime, game_port=39770, admin_port=39771)
    prepared.close()
