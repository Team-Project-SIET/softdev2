"""Controlled bootstrap seams; never start an OpenTTD world."""

import subprocess
from pathlib import Path

import pytest

from app.simulation.openttd.runtime.external import ExternalRuntime


def test_explicit_binary_identity(tmp_path: Path, monkeypatch) -> None:
    binary = tmp_path / "openttd"
    binary.write_bytes(b"abc")
    binary.chmod(0o700)
    calls = []

    def inspect(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, b"OpenTTD 15.3\n", b"")

    monkeypatch.setattr(subprocess, "run", inspect)
    runtime = ExternalRuntime.inspect(binary)
    assert calls == [[str(binary.resolve()), "--version"]]
    assert runtime.identity.backend == "external"
    assert runtime.identity.executable == binary.resolve()
    assert runtime.identity.version == "15.3"
    assert (
        runtime.identity.sha256
        == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert runtime.inspection.stdout == b"OpenTTD 15.3\n"
    assert runtime.inspection.stderr == b""
    assert runtime.inspection.exit_code == 0
    assert ExternalRuntime.inspect(binary).identity == runtime.identity


@pytest.mark.parametrize("kind", ["missing", "directory", "non_executable"])
def test_invalid_binary_never_inspected(tmp_path: Path, monkeypatch, kind: str) -> None:
    path = tmp_path / "invalid"
    if kind == "directory":
        path.mkdir()
    elif kind == "non_executable":
        path.write_bytes(b"abc")
        path.chmod(0o600)

    def forbidden(*args, **kwargs):
        pytest.fail("invalid binary must not execute or fall back")

    monkeypatch.setattr(subprocess, "run", forbidden)
    with pytest.raises((ValueError, FileNotFoundError)):
        ExternalRuntime.inspect(path)


@pytest.mark.parametrize(
    "output,code",
    [
        (b"OpenTTD 13.4\n", 0),
        (b"OpenTTD 15.3-RC1\n", 0),
        (b"OpenTTD 15.3\n", 1),
        (b"junk\nOpenTTD 15.3\n", 0),
    ],
)
def test_wrong_version_or_failed_inspection_rejected(
    tmp_path: Path, monkeypatch, output, code
) -> None:
    path = tmp_path / "openttd"
    path.write_bytes(b"abc")
    path.chmod(0o700)
    monkeypatch.setattr(
        subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, code, output, b"")
    )
    with pytest.raises(ValueError):
        ExternalRuntime.inspect(path)


def test_isolated_workspace_and_launch_spec(tmp_path: Path, monkeypatch) -> None:
    from app.simulation.openttd.runtime.config import AdminSettings, RuntimeWorkspace
    from app.simulation.openttd.runtime.identity import RuntimeIdentity, VersionInspection

    home = tmp_path / "user"
    normal = home / ".config/openttd"
    normal.mkdir(parents=True)
    marker = normal / "openttd.cfg"
    marker.write_text("user config")
    monkeypatch.setenv("HOME", str(home))
    identity = RuntimeIdentity(Path("/explicit/openttd"), "15.3", "a" * 64)
    runtime = ExternalRuntime(identity, VersionInspection((), b"", b"", 0))
    first = RuntimeWorkspace.create(tmp_path / "proof")
    second = RuntimeWorkspace.create(tmp_path / "proof")
    try:
        spec = runtime.prepare(first, admin=AdminSettings(password="proof-secret"), seed=17)
        other = runtime.prepare(second, admin=AdminSettings(password="proof-secret"), seed=17)
        assert spec.identity == other.identity == identity
        assert first.root != second.root
        assert spec.argv[0] == "/explicit/openttd"
        assert spec.argv[spec.argv.index("-c") + 1] == str(first.config)
        assert spec.argv[1] == "-D127.0.0.1:3979"
        assert spec.argv == (
            "/explicit/openttd",
            "-D127.0.0.1:3979",
            "-c",
            str(first.config),
            "-x",
            "-X",
            "-g",
            "-G",
            "17",
        )
        assert first.config.is_relative_to(first.root)
        assert "server_admin_port = 3977" in first.config.read_text()
        assert (
            (first.root / "private.cfg")
            .read_text()
            .endswith("[server_bind_addresses]\n127.0.0.1\n")
        )
        assert "proof-secret" in (first.root / "secrets.cfg").read_text()
        assert "proof-secret" not in repr(spec)
        assert first.game == first.root / "game"
        assert first.game.is_dir() and first.ai.is_dir()
        assert first.save == first.root / "save"
        assert first.autosave == first.save / "autosave"
        assert spec.stdout_path == first.logs / "stdout.log"
        assert spec.stderr_path == first.logs / "stderr.log"
        assert dict(spec.environment)["HOME"] == str(first.root / "home")
        assert marker.read_text() == "user config"
        assert not (home / ".local/share/openttd").exists()
        assert spec.lifecycle.graceful_command == b"quit\n"
        assert spec.lifecycle.pid is None
        assert spec.gamescript_api_major == "15"
    finally:
        first.close()
        first.close()
        second.close()
    assert not first.root.exists()


def test_15_3_version_help_exit_one(tmp_path: Path, monkeypatch) -> None:
    output = Path("tests/fixtures/openttd_15_3_version.stdout").read_bytes()
    path = tmp_path / "openttd"
    path.write_bytes(b"abc")
    path.chmod(0o700)
    monkeypatch.setattr(
        subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 1, output, b"")
    )
    runtime = ExternalRuntime.inspect(path)
    assert runtime.identity.version == "15.3"
    assert runtime.inspection.exit_code == 1


def test_owned_cleanup_reaps_before_removing_workspace(tmp_path: Path) -> None:
    import io

    from app.simulation.openttd.runtime.config import AdminSettings, RuntimeWorkspace
    from app.simulation.openttd.runtime.identity import RuntimeIdentity, VersionInspection

    workspace = RuntimeWorkspace.create(tmp_path)
    runtime = ExternalRuntime(
        RuntimeIdentity(Path("/explicit/openttd"), "15.3", "a" * 64),
        VersionInspection((), b"", b"", 0),
    )
    spec = runtime.prepare(workspace, admin=AdminSettings(password="proof"), seed=17)

    class Process:
        pid = 1234
        stdin = io.BytesIO()
        events = []

        def poll(self):
            return None

        def wait(self, timeout=None):
            assert workspace.root.is_dir()
            self.events.append("wait")
            assert self.stdin.getvalue() == b"quit\n"
            return 0

        def send_signal(self, requested):
            pytest.fail("graceful quit should succeed")

        def kill(self):
            pytest.fail("graceful quit should succeed")

    process = Process()
    spec.lifecycle.process = process
    assert spec.lifecycle.pid == 1234
    spec.close()
    spec.close()
    assert process.events == ["wait"]
    assert process.stdin.closed
    assert not workspace.root.exists()


@pytest.mark.parametrize(
    "seed,save", [(None, None), (17, "world.sav"), (-1, None), (2**32, None), (2**32 - 1, None)]
)
def test_world_selection_must_be_explicit_and_valid(tmp_path: Path, seed, save) -> None:
    from app.simulation.openttd.runtime.config import AdminSettings, RuntimeWorkspace
    from app.simulation.openttd.runtime.identity import RuntimeIdentity, VersionInspection

    runtime = ExternalRuntime(
        RuntimeIdentity(Path("/explicit/openttd"), "15.3", "a" * 64),
        VersionInspection((), b"", b"", 0),
    )
    workspace = RuntimeWorkspace.create(tmp_path)
    try:
        with pytest.raises(ValueError):
            runtime.prepare(
                workspace,
                admin=AdminSettings(password="proof"),
                seed=seed,
                savegame=Path(save) if save else None,
            )
        assert not workspace.config.exists()
    finally:
        workspace.close()


def test_save_selection_and_secret_permissions(tmp_path: Path) -> None:
    from app.simulation.openttd.runtime.config import AdminSettings, RuntimeWorkspace
    from app.simulation.openttd.runtime.identity import RuntimeIdentity, VersionInspection

    runtime = ExternalRuntime(
        RuntimeIdentity(Path("/explicit/openttd"), "15.3", "a" * 64),
        VersionInspection((), b"", b"", 0),
    )
    workspace = RuntimeWorkspace.create(tmp_path)
    save = workspace.save / "world.sav"
    save.write_bytes(b"controlled save placeholder")
    spec = runtime.prepare(workspace, admin=AdminSettings(password="proof"), savegame=save)
    assert spec.argv[-2:] == ("-g", str(save))
    assert "-G" not in spec.argv
    assert (workspace.root / "secrets.cfg").stat().st_mode & 0o777 == 0o600
    spec.close()


@pytest.mark.parametrize(
    "options",
    [
        dict(bind_address="0.0.0.0"),
        dict(port=0),
        dict(port=3979),
        dict(password=""),
        dict(password="x\n[network]"),
        dict(password="x" * 33),
    ],
)
def test_invalid_admin_settings_rejected(options) -> None:
    from app.simulation.openttd.runtime.config import AdminSettings

    with pytest.raises(ValueError):
        AdminSettings(**({"password": "proof"} | options))


@pytest.mark.parametrize("profile", [".config/openttd", ".local/share/openttd"])
def test_workspace_rejects_user_profile(tmp_path: Path, monkeypatch, profile: str) -> None:
    from app.simulation.openttd.runtime.config import RuntimeWorkspace

    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(ValueError):
        RuntimeWorkspace.create(tmp_path / profile / "proof")
    assert not (tmp_path / profile).exists()


def test_forced_cleanup_is_bounded_and_idempotent() -> None:
    import io
    import signal

    from app.simulation.openttd.runtime.base import ProcessLifecycle

    class Process:
        pid = 1234
        stdin = io.BytesIO()
        events = []
        killed = False

        def poll(self):
            return None

        def wait(self, timeout=None):
            self.events.append(("wait", timeout))
            if not self.killed:
                assert timeout is not None
                raise subprocess.TimeoutExpired("controlled", timeout)
            return -9

        def send_signal(self, requested):
            self.events.append(requested)

        def kill(self):
            self.events.append("kill")
            self.killed = True

    process = Process()
    lifecycle = ProcessLifecycle(process)
    lifecycle.close()
    lifecycle.close()
    assert process.events == [("wait", 5.0), signal.SIGTERM, ("wait", 5.0), "kill", ("wait", 5.0)]
    assert process.stdin.closed
    assert lifecycle.pid is None


def test_runtime_import_boundaries() -> None:
    import ast

    for path in Path("app/planning").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("app.simulation.openttd.runtime")
            if isinstance(node, ast.Import):
                assert not any(
                    alias.name.startswith("app.simulation.openttd.runtime") for alias in node.names
                )
    for path in Path("app/simulation/openttd/runtime").glob("*.py"):
        assert "openttdlab" not in path.read_text().lower()


def test_reaped_process_cleanup_survives_broken_stdin(tmp_path: Path) -> None:
    import io

    from app.simulation.openttd.runtime.base import ProcessLifecycle

    class BrokenStream(io.BytesIO):
        def write(self, value):
            raise BrokenPipeError

        def flush(self):
            raise BrokenPipeError

        def close(self):
            if not self.closed:
                super().close()
                raise BrokenPipeError

    class Process:
        pid = 123
        stdin = BrokenStream()

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

        def send_signal(self, requested):
            pass

        def kill(self):
            pytest.fail("reaped process must not be killed")

    lifecycle = ProcessLifecycle(Process())
    lifecycle.close()
    lifecycle.close()
    assert lifecycle.pid is None
