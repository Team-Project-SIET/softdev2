"""Only a marked and confirmed abandoned workspace can be removed."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.experiments.workspace_recovery import (
    WorkspaceOwner,
    cleanup_abandoned_workspaces,
    record_workspace_owner,
)


def test_active_workspace_is_retained_then_cleaned_after_owned_group_exits(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    workspace = root / ".live-workspaces/live-controlled"
    workspace.mkdir(parents=True)
    workspace.chmod(0o700)
    secret = workspace / "secrets.cfg"
    secret.write_text("controlled secret")
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
    )
    try:
        record_workspace_owner(workspace, 7, process.pid)
        assert cleanup_abandoned_workspaces(root, 7)
        assert secret.exists()
    finally:
        process.terminate()
        process.wait(timeout=5)
    assert not cleanup_abandoned_workspaces(root, 7)
    assert not workspace.exists()


def test_unmarked_workspace_and_other_run_remain_untouched(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    workspace = root / ".live-workspaces/live-old"
    workspace.mkdir(parents=True)
    (workspace / "secrets.cfg").write_text("controlled old secret")
    assert not cleanup_abandoned_workspaces(root, 7)
    assert workspace.exists()


def test_stale_pid_identity_never_signals_or_removes_an_active_group(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "artifacts"
    workspace = root / ".live-workspaces/live-stale"
    workspace.mkdir(parents=True)
    workspace.chmod(0o700)
    marker = WorkspaceOwner(run_id=7, process_group_id=os.getpgrp(), process_start_ticks=1)
    path = workspace / "owner-v1.json"
    path.write_text(marker.model_dump_json())
    path.chmod(0o600)

    def forbidden_signal(*args, **kwargs):
        raise AssertionError("recovery must not signal an old process group")

    monkeypatch.setattr(os, "killpg", forbidden_signal)
    assert cleanup_abandoned_workspaces(root, 7)
    assert workspace.exists()


def test_name_swap_during_fd_erase_never_erases_replacement(tmp_path: Path, monkeypatch) -> None:
    from app.experiments import workspace_recovery

    root = tmp_path / "artifacts"
    workspace = root / ".live-workspaces/live-owned"
    workspace.mkdir(parents=True)
    workspace.chmod(0o700)
    marker = WorkspaceOwner(run_id=7, process_group_id=2**30, process_start_ticks=1)
    marker_path = workspace / "owner-v1.json"
    marker_path.write_text(marker.model_dump_json())
    marker_path.chmod(0o600)
    real_erase = workspace_recovery._erase_contents
    swapped = False

    def swap_before_erase(directory_fd: int) -> None:
        nonlocal swapped
        if not swapped:
            swapped = True
            os.rename(workspace, workspace.parent / "live-original")
            workspace.mkdir()
            (workspace / "secrets.cfg").write_text("unrelated active secret")
        real_erase(directory_fd)

    monkeypatch.setattr(workspace_recovery, "_erase_contents", swap_before_erase)
    assert cleanup_abandoned_workspaces(root, 7)
    assert (workspace / "secrets.cfg").read_text() == "unrelated active secret"
    assert not list(workspace.parent.glob(".recovery-*"))


def test_erase_failure_leaves_marked_workspace_retryable(tmp_path: Path, monkeypatch) -> None:
    from app.experiments import workspace_recovery

    root = tmp_path / "artifacts"
    workspace = root / ".live-workspaces/live-retry"
    workspace.mkdir(parents=True)
    workspace.chmod(0o700)
    marker = WorkspaceOwner(run_id=7, process_group_id=2**30, process_start_ticks=1)
    marker_path = workspace / "owner-v1.json"
    marker_path.write_text(marker.model_dump_json())
    marker_path.chmod(0o600)
    (workspace / "secrets.cfg").write_text("controlled secret")
    real_erase = workspace_recovery._erase_contents

    def fail_once(directory_fd: int) -> None:
        monkeypatch.setattr(workspace_recovery, "_erase_contents", real_erase)
        raise OSError("controlled erase failure")

    monkeypatch.setattr(workspace_recovery, "_erase_contents", fail_once)
    with pytest.raises(OSError, match="erase failure"):
        cleanup_abandoned_workspaces(root, 7)
    assert marker_path.exists()
    assert not cleanup_abandoned_workspaces(root, 7)
    assert not workspace.exists()


@pytest.mark.parametrize("stat_denied", [False, True])
def test_unreadable_live_proc_entry_keeps_workspace(
    tmp_path: Path, monkeypatch, stat_denied: bool
) -> None:
    from app.experiments import workspace_recovery

    root = tmp_path / "artifacts"
    workspace = root / ".live-workspaces/live-unverified"
    workspace.mkdir(parents=True)
    workspace.chmod(0o700)
    marker = WorkspaceOwner(run_id=7, process_group_id=2**30, process_start_ticks=1)
    marker_path = workspace / "owner-v1.json"
    marker_path.write_text(marker.model_dump_json())
    marker_path.chmod(0o600)
    real_identity = workspace_recovery._process_identity

    def unreadable_own_entry(pid: int):
        return None if pid == os.getpid() else real_identity(pid)

    monkeypatch.setattr(workspace_recovery, "_process_identity", unreadable_own_entry)
    if stat_denied:
        original_stat = Path.stat

        def denied_stat(path: Path, *args, **kwargs):
            if path == Path("/proc") / str(os.getpid()):
                raise PermissionError("controlled procfs denial")
            return original_stat(path, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", denied_stat)
    assert cleanup_abandoned_workspaces(root, 7)
    assert marker_path.exists()
