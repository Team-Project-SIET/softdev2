"""Conservative cleanup of marked, abandoned live secret workspaces."""

import errno
import os
import re
import stat
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.experiments.outcome_manifest import _open_directory_chain


class WorkspaceOwner(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = Field(default=1, ge=1, le=1)
    run_id: int = Field(gt=0)
    process_group_id: int = Field(gt=0)
    process_start_ticks: int = Field(gt=0)


def _process_identity(pid: int) -> tuple[int, int] | None:
    try:
        raw = (Path("/proc") / str(pid) / "stat").read_text(encoding="ascii")
        fields = raw.rsplit(") ", 1)[1].split()
        return int(fields[2]), int(fields[19])
    except IndexError, OSError, ValueError:
        return None


def record_workspace_owner(workspace: Path, run_id: int, process_pid: int) -> None:
    """Record only a process identity; never record credentials or argv."""
    identity = _process_identity(process_pid)
    if identity is None or identity[0] != process_pid:
        raise ValueError("owned process group identity unavailable")
    marker = WorkspaceOwner(
        run_id=run_id,
        process_group_id=process_pid,
        process_start_ticks=identity[1],
    )
    directory_fd = _open_directory_chain(workspace.absolute())
    try:
        marker_fd = os.open(
            "owner-v1.json",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
        with os.fdopen(marker_fd, "wb") as stream:
            stream.write((marker.model_dump_json() + "\n").encode("ascii"))
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _group_may_be_alive(group_id: int) -> bool:
    """Fail closed if procfs cannot establish that the old group is absent."""
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return True
    for entry in entries:
        if not entry.name.isdecimal():
            continue
        identity = _process_identity(int(entry.name))
        if identity is None:
            try:
                entry.stat()
            except FileNotFoundError:
                continue
            except OSError:
                return True
            return True
        if identity[0] == group_id:
            return True
    return False


def _erase_contents(directory_fd: int) -> None:
    """Remove entries through the verified directory handle without following links."""
    for name in os.listdir(directory_fd):
        try:
            child_fd = os.open(
                name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd
            )
        except NotADirectoryError:
            os.unlink(name, dir_fd=directory_fd)
            continue
        except OSError as exc:
            if exc.errno == errno.ELOOP:  # A symlink, never a directory to traverse.
                os.unlink(name, dir_fd=directory_fd)
                continue
            raise
        try:
            _erase_contents(child_fd)
        finally:
            os.close(child_fd)
        os.rmdir(name, dir_fd=directory_fd)


def _remove_verified_workspace(workspaces_fd: int, name: str, workspace_fd: int) -> bool:
    """Erase only through the verified fd; retain the name if it has changed."""
    original = os.fstat(workspace_fd)
    _erase_contents(workspace_fd)
    try:
        current = os.stat(name, dir_fd=workspaces_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    if (current.st_dev, current.st_ino) != (original.st_dev, original.st_ino):
        return False
    try:
        os.rmdir(name, dir_fd=workspaces_fd)
    except OSError:
        return False
    return True


def cleanup_abandoned_workspaces(artifact_root: Path, run_id: int) -> bool:
    """Remove marked workspaces for this run only; return True if any remain unverified."""
    root_fd = _open_directory_chain(artifact_root.absolute())
    try:
        try:
            workspaces_fd = os.open(
                ".live-workspaces",
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=root_fd,
            )
        except FileNotFoundError:
            return False
        try:
            pending = False
            for name in os.listdir(workspaces_fd):
                if re.fullmatch(r"live-[A-Za-z0-9_-]+", name) is None:
                    continue
                try:
                    workspace_fd = os.open(
                        name,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=workspaces_fd,
                    )
                except OSError:
                    continue
                try:
                    workspace_info = os.fstat(workspace_fd)
                    if (
                        workspace_info.st_uid != os.getuid()
                        or stat.S_IMODE(workspace_info.st_mode) != 0o700
                    ):
                        continue
                    try:
                        marker_fd = os.open(
                            "owner-v1.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=workspace_fd
                        )
                    except OSError:
                        continue  # Older or unverifiable workspace: retain it.
                    with os.fdopen(marker_fd, "rb") as marker_file:
                        marker_info = os.fstat(marker_file.fileno())
                        if (
                            not stat.S_ISREG(marker_info.st_mode)
                            or marker_info.st_uid != os.getuid()
                            or stat.S_IMODE(marker_info.st_mode) != 0o600
                        ):
                            continue
                        data = marker_file.read(513)
                    if len(data) > 512:
                        continue
                    try:
                        owner = WorkspaceOwner.model_validate_json(data)
                    except ValidationError:
                        continue
                    if owner.run_id != run_id:
                        continue
                    if _process_identity(owner.process_group_id) == (
                        owner.process_group_id,
                        owner.process_start_ticks,
                    ):
                        pending = True
                        continue
                    if _group_may_be_alive(owner.process_group_id):
                        pending = True
                        continue
                    current = os.stat(name, dir_fd=workspaces_fd, follow_symlinks=False)
                    opened = os.fstat(workspace_fd)
                    if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
                        pending = True
                        continue
                    if not _remove_verified_workspace(workspaces_fd, name, workspace_fd):
                        pending = True
                finally:
                    os.close(workspace_fd)
            return pending
        finally:
            os.close(workspaces_fd)
    finally:
        os.close(root_fd)
