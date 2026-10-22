"""Controlled console/file seam; no OpenTTD launch or connection."""

import asyncio
import hashlib
import shlex
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.simulation.openttd.proof import road_mutation as driver


def setup(tmp_path, monkeypatch, *, relative=False):
    monkeypatch.chdir(tmp_path)
    artifact = tmp_path / "authorized-artifacts"
    artifact.mkdir()
    native = tmp_path / "custom-config" / "save"
    native.mkdir(parents=True)
    stdout, stderr = tmp_path / "stdout", tmp_path / "stderr"
    stdout.write_text("")
    stderr.write_text("")
    prepared = SimpleNamespace(
        directory=Path("authorized-artifacts") if relative else artifact,
        spec=SimpleNamespace(stdout_path=stdout, stderr_path=stderr),
    )
    backend = SimpleNamespace(health=lambda: None)
    commands = []

    def console(_, command):
        commands.append(command)
        _, requested = shlex.split(command)
        # ConSave appends .sav. Relative names are resolved by native file I/O.
        path = Path(requested + ".sav")
        if not path.is_absolute():
            path = native / path
        path.write_bytes(b"controlled save bytes")
        stdout.write_text(f"Map successfully saved to '{path}'.\n")

    monkeypatch.setattr(driver, "console", console)
    return prepared, backend, artifact, commands


@pytest.mark.parametrize("relative", [False, True])
def test_save_uses_absolute_native_name_and_verifies_bytes(tmp_path, monkeypatch, relative):
    prepared, backend, artifact, commands = setup(tmp_path, monkeypatch, relative=relative)
    digest = asyncio.run(driver.save(backend, prepared, "canonical"))
    assert digest == hashlib.sha256(b"controlled save bytes").hexdigest()
    assert commands == [f'save "{artifact}/canonical"']
    assert (artifact / "canonical.sav").is_file()


@pytest.mark.parametrize(
    "name", ["../escaped", "/escaped", "nested/name", "canonical.sav", "a\nb", 'a"b', "", "."]
)
def test_invalid_native_name_never_sends_console(tmp_path, monkeypatch, name):
    prepared, backend, _, commands = setup(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        asyncio.run(driver.save(backend, prepared, name))
    assert not commands


@pytest.mark.parametrize("kind", ["file", "directory", "symlink", "broken_symlink"])
def test_collision_never_sends_console(tmp_path, monkeypatch, kind):
    prepared, backend, artifact, commands = setup(tmp_path, monkeypatch)
    target = artifact / "canonical.sav"
    if kind == "file":
        target.write_bytes(b"historical")
    elif kind == "directory":
        target.mkdir()
    else:
        target.symlink_to(artifact / ("missing" if kind == "broken_symlink" else "."))
    with pytest.raises(ValueError):
        asyncio.run(driver.save(backend, prepared, "canonical"))
    assert not commands


@pytest.mark.parametrize(
    "defect", ["missing", "symlink", "directory", "empty", "duplicate", "wrong"]
)
def test_completion_must_match_new_regular_save(tmp_path, monkeypatch, defect):
    prepared, backend, artifact, _ = setup(tmp_path, monkeypatch)
    target = artifact / "canonical.sav"

    def console(_, command):
        if defect == "symlink":
            other = tmp_path / "outside.sav"
            other.write_bytes(b"outside")
            target.symlink_to(other)
        elif defect == "directory":
            target.mkdir()
        elif defect != "missing":
            target.write_bytes(b"" if defect == "empty" else b"save")
        marker = f"Map successfully saved to '{target}'.\n"
        if defect == "wrong":
            marker = f"Map successfully saved to '{target}.extra'.\n"
        prepared.spec.stdout_path.write_text(marker * (2 if defect == "duplicate" else 1))

    monkeypatch.setattr(driver, "console", console)
    ticks = iter([0, 20])
    monkeypatch.setattr(driver, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    with pytest.raises((ValueError, TimeoutError)):
        asyncio.run(driver.save(backend, prepared, "canonical"))


def test_old_completion_cannot_acknowledge_new_save(tmp_path, monkeypatch):
    prepared, backend, artifact, _ = setup(tmp_path, monkeypatch)
    target = artifact / "canonical.sav"
    prepared.spec.stdout_path.write_text(f"Map successfully saved to '{target}'.\n")
    monkeypatch.setattr(driver, "console", lambda *_: target.write_bytes(b"unacknowledged"))
    ticks = iter([0, 20])
    monkeypatch.setattr(driver, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    with pytest.raises(TimeoutError):
        asyncio.run(driver.save(backend, prepared, "canonical"))


def test_symlink_artifact_directory_rejected(tmp_path, monkeypatch):
    prepared, backend, artifact, commands = setup(tmp_path, monkeypatch)
    alias = tmp_path / "alias"
    alias.symlink_to(artifact, target_is_directory=True)
    prepared.directory = alias
    with pytest.raises(ValueError):
        asyncio.run(driver.save(backend, prepared, "canonical"))
    assert not commands


def test_failed_diagnostic_save_preserves_startup_error_and_cleanup(tmp_path, monkeypatch):
    import json

    from app.simulation.openttd.proof import canonical_fleet

    root = tmp_path / "isolated"
    logs = root / "logs"
    logs.mkdir(parents=True)
    key = root / ".admin-secret"
    key.write_bytes(b"controlled-secret")

    def close():
        key.unlink()
        logs.rmdir()
        root.rmdir()

    prepared = SimpleNamespace(
        directory=tmp_path,
        key_path=key,
        spec=SimpleNamespace(workspace=SimpleNamespace(root=root, logs=logs, close=close)),
    )
    (tmp_path / "PRELAUNCH.json").write_text("{}")
    events = []

    class Backend:
        process = object()

        async def launch(self, prepared):
            events.append("launch")
            raise RuntimeError("original startup command failure")

        async def cleanup(self, prepared):
            events.append("cleanup")
            return dict(reaped=True, sockets_closed=True, cleanup_error=[], remaining_processes=[])

    async def failed_save(backend, prepared, name):
        events.append("save-" + name)
        raise ValueError("native save command failed")

    monkeypatch.setattr(canonical_fleet, "CanonicalBackend", lambda **_: Backend())
    monkeypatch.setattr(canonical_fleet, "preflight", lambda _: {"budgets": {"total_seconds": 1}})
    monkeypatch.setattr(canonical_fleet, "verify_cleanup_endpoints", lambda *_: {})
    monkeypatch.setattr(canonical_fleet, "protected_save", failed_save)
    result = asyncio.run(canonical_fleet.run(prepared, authorize_one_launch=True))
    assert result["error"] == "RuntimeError: original startup command failure"
    assert result["failure_save_error"] == "native save command failed"
    assert events == ["launch", "save-failure", "cleanup"]
    assert not root.exists()
    assert json.loads((tmp_path / "cleanup.json").read_text())["credential_removed"]
    assert (tmp_path / "artifact-manifest.sha256").exists()


def test_absolute_save_path_with_spaces_is_one_console_argument(tmp_path, monkeypatch):
    prepared, backend, artifact, commands = setup(tmp_path, monkeypatch)
    spaced = tmp_path / "authorized artifacts"
    artifact.rename(spaced)
    prepared.directory = spaced
    assert (
        asyncio.run(driver.save(backend, prepared, "before"))
        == hashlib.sha256(b"controlled save bytes").hexdigest()
    )
    assert commands == [f'save "{spaced}/before"']


def test_native_save_failure_is_reported_without_waiting_for_missing_file(tmp_path, monkeypatch):
    prepared, backend, _, _ = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(
        driver,
        "console",
        lambda *_: prepared.spec.stdout_path.write_text("Saving map failed.\n"),
    )
    with pytest.raises(ValueError, match="native save command failed"):
        asyncio.run(driver.save(backend, prepared, "failure"))


def test_real_failure_save_seam_ignores_prior_script_fatal_only(tmp_path, monkeypatch):
    import json

    from app.simulation.openttd.proof import canonical_fleet
    from app.simulation.openttd.proof.native import NativeBackend

    prepared, _, artifact, commands = setup(tmp_path, monkeypatch)
    root = artifact / "isolated"
    logs = root / "logs"
    logs.mkdir(parents=True)
    key = root / ".admin-secret"
    key.write_bytes(b"controlled-secret")
    prepared.key_path = key
    prepared.spec.stdout_path = logs / "stdout.log"
    prepared.spec.stderr_path = logs / "stderr.log"
    prepared.spec.stdout_path.write_text("")
    prepared.spec.stderr_path.write_text("The script died unexpectedly\n")

    def close():
        for path in logs.iterdir():
            path.unlink()
        logs.rmdir()
        key.unlink()
        root.rmdir()

    def console(_, command):
        commands.append(command)
        _, requested = shlex.split(command)
        path = Path(requested + ".sav")
        path.write_bytes(b"controlled save bytes")
        prepared.spec.stdout_path.write_text(f"Map successfully saved to '{path}'.\n")

    monkeypatch.setattr(driver, "console", console)
    prepared.spec.workspace = SimpleNamespace(root=root, logs=logs, close=close)
    (artifact / "PRELAUNCH.json").write_text("{}")

    class Backend:
        process = SimpleNamespace(poll=lambda: None)
        _prepared = prepared
        health = NativeBackend.health
        _check_logs = NativeBackend._check_logs

        async def launch(self, value):
            self.health()

        async def cleanup(self, value):
            return dict(reaped=True, sockets_closed=True, cleanup_error=[], remaining_processes=[])

    monkeypatch.setattr(canonical_fleet, "CanonicalBackend", lambda **_: Backend())
    monkeypatch.setattr(canonical_fleet, "preflight", lambda _: {"budgets": {"total_seconds": 1}})
    monkeypatch.setattr(canonical_fleet, "verify_cleanup_endpoints", lambda *_: {})
    result = asyncio.run(canonical_fleet.run(prepared, authorize_one_launch=True))
    assert result["error"] == "RuntimeError: Native script/asset error"
    assert "failure_save_error" not in result
    assert (artifact / "failure.sav").read_bytes() == b"controlled save bytes"
    assert len(commands) == 1
    assert not root.exists()
    assert json.loads((artifact / "cleanup.json").read_text())["credential_removed"]


def test_diagnostic_save_rejects_dead_process_before_console(tmp_path, monkeypatch):
    prepared, backend, _, commands = setup(tmp_path, monkeypatch)
    backend.process = SimpleNamespace(poll=lambda: 1)
    with pytest.raises(RuntimeError, match="exited before diagnostic save"):
        asyncio.run(driver.save(backend, prepared, "failure", diagnostic=True))
    assert not commands


def test_normal_save_still_rejects_prior_script_error(tmp_path, monkeypatch):
    prepared, backend, _, _ = setup(tmp_path, monkeypatch)

    def health():
        raise RuntimeError("Native script/asset error")

    backend.health = health
    with pytest.raises(RuntimeError, match="Native script/asset error"):
        asyncio.run(driver.save(backend, prepared, "canonical"))


def test_diagnostic_save_still_rejects_fresh_save_command_error(tmp_path, monkeypatch):
    prepared, backend, _, _ = setup(tmp_path, monkeypatch)
    backend.process = SimpleNamespace(poll=lambda: None)
    prepared.spec.stderr_path.write_text("The script died unexpectedly\n")
    monkeypatch.setattr(
        driver,
        "console",
        lambda *_: prepared.spec.stdout_path.write_text("Saving map failed.\n"),
    )
    with pytest.raises(ValueError, match="native save command failed"):
        asyncio.run(driver.save(backend, prepared, "failure", diagnostic=True))
