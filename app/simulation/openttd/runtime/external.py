"""Explicit 15.3 executable inspection; no discovery, download, or gameplay launch."""

import hashlib
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .base import LaunchSpecification
from .config import AdminSettings, RuntimeWorkspace
from .identity import RuntimeIdentity, VersionInspection


@dataclass(frozen=True)
class ExternalRuntime:
    identity: RuntimeIdentity
    inspection: VersionInspection

    @classmethod
    def inspect(cls, executable: Path) -> ExternalRuntime:
        resolved = executable.expanduser().resolve(strict=True)
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            raise ValueError("OpenTTD must be a regular executable file")
        with resolved.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        argv = (str(resolved), "--version")
        # --version enters 15.3's help path, which also determines directories.
        # Isolate HOME/XDG and cwd even for this non-gameplay inspection.
        with tempfile.TemporaryDirectory(prefix="openttd-version-") as directory:
            root = Path(directory)
            environment = os.environ.copy()
            for name, relative in (
                ("HOME", "home"),
                ("XDG_CONFIG_HOME", "config"),
                ("XDG_DATA_HOME", "data"),
                ("XDG_CACHE_HOME", "cache"),
            ):
                target = root / relative
                target.mkdir()
                environment[name] = str(target)
            result = subprocess.run(
                list(argv),
                capture_output=True,
                timeout=10,
                check=False,
                cwd=root,
                env=environment,
                stdin=subprocess.DEVNULL,
            )
        inspection = VersionInspection(argv, result.stdout, result.stderr, result.returncode)
        version = parse_version(result.stdout.decode("utf-8"))
        help_exit = (
            result.returncode == 1
            and result.stdout.startswith(b"OpenTTD 15.3\n\n\nCommand line options:\n")
            and b"List of Game Scripts:" in result.stdout
            and result.stderr == b""
        )
        if (result.returncode != 0 and not help_exit) or version != "15.3":
            raise ValueError("External runtime requires exactly OpenTTD 15.3")
        with resolved.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                raise ValueError("Executable changed during version inspection")
        return cls(RuntimeIdentity(resolved, version, digest), inspection)

    def prepare(
        self,
        workspace: RuntimeWorkspace,
        *,
        admin: AdminSettings,
        seed: int | None = None,
        savegame: Path | None = None,
    ) -> LaunchSpecification:
        """Generate files and argv only. World selection must be explicit."""
        if (seed is None) == (savegame is None):
            raise ValueError("Select exactly one deterministic seed or savegame")
        selection: tuple[str, ...]
        if seed is not None:
            if not 0 <= seed < 2**32 - 1:
                raise ValueError("Seed must be uint32 excluding the random-generation sentinel")
            selection = ("-g", "-G", str(seed))
        else:
            assert savegame is not None
            savegame = savegame.resolve(strict=True)
            if not savegame.is_file() or not savegame.is_relative_to(workspace.root):
                raise ValueError("Savegame must be a regular file inside the workspace")
            selection = ("-g", str(savegame))
        workspace.write_config(admin)
        return LaunchSpecification(
            workspace,
            self.identity,
            (
                str(self.identity.executable),
                f"-D127.0.0.1:{admin.game_port}",
                "-c",
                str(workspace.config),
                "-x",
                "-X",
                *selection,
            ),
            workspace.root,
            workspace.environment,
            workspace.logs / "stdout.log",
            workspace.logs / "stderr.log",
        )


def parse_version(stdout: str) -> str:
    match = re.match(r"OpenTTD ([^\s]+)(?:\n|$)", stdout)
    if match is None:
        raise ValueError("Unrecognized OpenTTD version output")
    return match.group(1)
