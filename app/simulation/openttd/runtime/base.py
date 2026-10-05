"""Launch specification and cleanup of an already-owned process; no launch entry point."""

import signal
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Protocol

from .config import RuntimeWorkspace
from .identity import RuntimeIdentity


class OwnedProcess(Protocol):
    @property
    def pid(self) -> int: ...

    @property
    def stdin(self) -> IO[bytes] | None: ...

    def poll(self) -> int | None: ...
    def wait(self, timeout: float | None = None) -> int: ...
    def send_signal(self, requested: signal.Signals, /) -> None: ...
    def kill(self) -> None: ...


@dataclass
class ProcessLifecycle:
    """An authorized future launcher supplies its process, with stdin piped."""

    process: OwnedProcess | None = field(default=None, repr=False)
    graceful_command: bytes = b"quit\n"
    timeout_seconds: float = 5.0
    events: list[str] = field(default_factory=list)

    @property
    def pid(self) -> int | None:
        return None if self.process is None else self.process.pid

    def close(self) -> None:
        process = self.process
        if process is None:
            return
        if process.poll() is None:
            try:
                if process.stdin is not None:
                    self.events.append("quit_requested")
                    process.stdin.write(self.graceful_command)
                    process.stdin.flush()
                else:
                    self.events.append("sigterm_requested")
                    process.send_signal(signal.SIGTERM)
                process.wait(timeout=self.timeout_seconds)
            except OSError, ValueError, subprocess.TimeoutExpired:
                try:
                    self.events.append("sigterm_requested")
                    process.send_signal(signal.SIGTERM)
                    process.wait(timeout=self.timeout_seconds)
                except OSError, subprocess.TimeoutExpired:
                    self.events.append("kill_requested")
                    process.kill()
                    process.wait(timeout=self.timeout_seconds)
        else:
            process.wait(timeout=self.timeout_seconds)
        self.events.append("reaped")
        self.process = None  # Successful wait above established ownership has ended.
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError, ValueError:
                pass  # A dead pipe must not prevent post-reap workspace cleanup.


@dataclass(frozen=True)
class LaunchSpecification:
    workspace: RuntimeWorkspace = field(repr=False)
    identity: RuntimeIdentity
    argv: tuple[str, ...]
    cwd: Path
    environment: tuple[tuple[str, str], ...]
    stdout_path: Path
    stderr_path: Path
    lifecycle: ProcessLifecycle = field(default_factory=ProcessLifecycle, compare=False)
    mode: str = "dedicated"
    stdin_pipe: bool = True
    start_new_session: bool = True
    gamescript_api_major: str = "15"

    def close(self) -> None:
        """Reap before removing files; failed process cleanup retains the workspace."""
        self.lifecycle.close()
        self.workspace.close()
