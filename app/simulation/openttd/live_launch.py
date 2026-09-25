"""OpenTTD 13.4 per-run files and local port ownership; no process launch."""

import configparser
import fcntl
import os
import re
import secrets
import shutil
import socket
import stat
import tempfile
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import IO

from app.experiments.domain import ExperimentConfig
from app.experiments.strategies import (
    BaselineStrategy,
    SimpleMultimodalStrategy,
    SimpleRoadOnlyStrategy,
)
from app.simulation.openttd.runtime_assets import PreparedRuntime


class LiveLaunchCode(StrEnum):
    INVALID_CONFIGURATION = "invalid_configuration"
    CONFLICTING_SETTING = "conflicting_owned_setting"
    INVALID_PORT = "invalid_fixed_port"
    PORT_IN_USE = "port_in_use"
    LEASE_CONFLICT = "port_lease_conflict"
    WORKSPACE_FAILURE = "workspace_creation_failure"
    PERMISSION_FAILURE = "permission_failure"
    SECRET_FAILURE = "secret_or_config_failure"
    UNSAFE_PATH = "unsafe_path"
    CLEANUP_FAILURE = "incomplete_cleanup"
    DEADLINE_EXCEEDED = "startup_deadline_exceeded"


class LiveLaunchError(RuntimeError):
    """Bounded, secret-free error crossing the preparation boundary."""

    def __init__(self, code: LiveLaunchCode) -> None:
        self.code = code
        super().__init__(code.value.replace("_", " "))


_DEFAULT_LOCK_ROOT = Path(tempfile.gettempdir()) / f"softdev2-openttd-ports-{os.getuid()}"
_AI_NAME = re.compile(r"[A-Za-z0-9_.-]+\Z")
_AI_PARAMETER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_INTEGER = re.compile(r"-?[0-9]+\Z")
_SCENARIO_SETTINGS = {"game_creation": {"map_x", "map_y", "starting_year"}}


def _check_deadline(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() >= deadline:
        raise LiveLaunchError(LiveLaunchCode.DEADLINE_EXCEEDED)


def _copy_runtime_file(source: Path, target: Path, deadline: float | None) -> None:
    with source.open("rb") as input_file, target.open("xb") as output_file:
        while chunk := input_file.read(1024 * 1024):
            _check_deadline(deadline)
            output_file.write(chunk)
    _check_deadline(deadline)


def _safe_save_name(name: str) -> str:
    if (
        not isinstance(name, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.sav", name)
        or ".." in name
    ):
        raise LiveLaunchError(LiveLaunchCode.UNSAFE_PATH)
    return name


def _scenario_settings(config: ExperimentConfig) -> dict[str, str]:
    text = config.scenario.openttd_config
    if not text:
        return {}
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        parser.read_string(text)
    except configparser.Error:
        raise LiveLaunchError(LiveLaunchCode.INVALID_CONFIGURATION) from None
    if parser.defaults():
        raise LiveLaunchError(LiveLaunchCode.INVALID_CONFIGURATION)
    for section in parser.sections():
        if section.lower() not in _SCENARIO_SETTINGS:
            code = (
                LiveLaunchCode.CONFLICTING_SETTING
                if section.lower() in {"network", "gui", "ai", "version", "ai_players"}
                else LiveLaunchCode.INVALID_CONFIGURATION
            )
            raise LiveLaunchError(code)
        for key, value in parser.items(section):
            if key not in _SCENARIO_SETTINGS[section.lower()]:
                raise LiveLaunchError(LiveLaunchCode.CONFLICTING_SETTING)
            if not _INTEGER.fullmatch(value) or int(value) < 0:
                raise LiveLaunchError(LiveLaunchCode.INVALID_CONFIGURATION)
            number = int(value)
            if key in {"map_x", "map_y"} and not 6 <= number <= 12:
                raise LiveLaunchError(LiveLaunchCode.INVALID_CONFIGURATION)
            if key == "starting_year" and not 1 <= number <= 9_999:
                raise LiveLaunchError(LiveLaunchCode.INVALID_CONFIGURATION)
    return dict(parser.items("game_creation")) if parser.has_section("game_creation") else {}


def _ai_line(config: ExperimentConfig) -> str:
    if not _AI_NAME.fullmatch(config.ai.name):
        raise LiveLaunchError(LiveLaunchCode.INVALID_CONFIGURATION)
    parameters = []
    for name, value in config.ai.parameters:
        if not _AI_PARAMETER.fullmatch(name) or not _INTEGER.fullmatch(value):
            raise LiveLaunchError(LiveLaunchCode.INVALID_CONFIGURATION)
        parameters.append(f"{name}={value}")
    return f"{config.ai.name} = {','.join(parameters)}"


def _write_owned(path: Path, content: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(content)


def _available(port: int, *, udp: bool) -> bool:
    kind = socket.SOCK_DGRAM if udp else socket.SOCK_STREAM
    try:
        with socket.socket(socket.AF_INET, kind) as candidate:
            candidate.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False


class PortLease:
    """Host-local advisory ownership, not an atomic claim against other programs.

    Bind-check sockets close before OpenTTD can start. T07 must verify its owned
    process acquired both expected endpoints before treating it as ready.
    """

    def __init__(self, game_port: int, admin_port: int, locks: tuple[IO[bytes], ...]) -> None:
        self.game_port = game_port
        self.admin_port = admin_port
        self._locks = locks
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        if self._closed:
            return
        failed = False
        for lock in reversed(self._locks):
            try:
                fcntl.flock(lock, fcntl.LOCK_UN)
            except OSError:
                failed = True
            try:
                lock.close()
            except OSError:
                failed = True
        self._closed = True
        if failed:
            raise LiveLaunchError(LiveLaunchCode.CLEANUP_FAILURE) from None


@dataclass
class PreparedLiveRuntime:
    """Future runner owns this until its process is confirmed reaped."""

    runtime: PreparedRuntime
    workspace: Path
    main_config_path: Path
    private_config_path: Path
    secrets_config_path: Path
    ai_archive_path: Path
    dependency_archive_paths: tuple[Path, ...]
    graphics_archive_path: Path
    final_save_path: Path
    admin_password: str = field(repr=False)
    lease: PortLease
    argv: tuple[str, ...]
    provenance: dict[str, object]

    @property
    def cwd(self) -> Path:
        return self.workspace

    @property
    def game_port(self) -> int:
        return self.lease.game_port

    @property
    def admin_port(self) -> int:
        return self.lease.admin_port

    def close(self) -> None:
        """Call only after future owned process exit; removes this workspace only."""
        failed = False
        try:
            shutil.rmtree(self.workspace)
        except FileNotFoundError:
            pass
        except OSError:
            failed = True
        try:
            self.lease.close()
        except LiveLaunchError:
            failed = True
        if failed:
            raise LiveLaunchError(LiveLaunchCode.CLEANUP_FAILURE) from None


class LiveLaunchPreparation:
    """Prepare one isolated 13.4 launch, then transfer the returned owner handle."""

    def __init__(
        self,
        workspace_root: Path,
        *,
        lock_root: Path = _DEFAULT_LOCK_ROOT,
        port_range: tuple[int, int] = (39770, 39999),
    ) -> None:
        self.workspace_root = workspace_root
        self.lock_root = lock_root
        self.port_range = port_range

    def prepare(
        self,
        config: ExperimentConfig,
        runtime: PreparedRuntime,
        *,
        game_port: int | None = None,
        admin_port: int | None = None,
        save_name: str = "final.sav",
        deadline: float | None = None,
    ) -> PreparedLiveRuntime:
        _check_deadline(deadline)
        scenario = _scenario_settings(config)
        ai_line = _ai_line(config)
        save_name = _safe_save_name(save_name)
        if config.openttd_version != "13.4" or config.opengfx_version != "7.1":
            raise LiveLaunchError(LiveLaunchCode.INVALID_CONFIGURATION)
        strategies = (BaselineStrategy(), SimpleRoadOnlyStrategy(), SimpleMultimodalStrategy())
        if not any(
            strategy.configure(config.scenario) == (config.planning, config.ai)
            for strategy in strategies
        ):
            raise LiveLaunchError(LiveLaunchCode.INVALID_CONFIGURATION)
        if runtime.ai_configuration != config.ai:
            raise LiveLaunchError(LiveLaunchCode.INVALID_CONFIGURATION)
        _check_deadline(deadline)
        lease = self._lease(game_port, admin_port, deadline)
        workspace: Path | None = None
        try:
            self.workspace_root.mkdir(parents=True, exist_ok=True)
            workspace = Path(tempfile.mkdtemp(prefix="live-", dir=self.workspace_root))
            workspace.chmod(0o700)
            for directory in ("save", "baseset", "ai", "ai/library"):
                (workspace / directory).mkdir(parents=True, exist_ok=True)
            final_save = workspace / "save" / save_name
            graphics = workspace / "baseset" / runtime.opengfx_archive_path.name
            ai_archive = workspace / "ai" / runtime.ai_archive_path.name
            dependencies = tuple(
                workspace / "ai/library" / path.name for path in runtime.dependency_archive_paths
            )
            for source, target in (
                (runtime.opengfx_archive_path, graphics),
                (runtime.ai_archive_path, ai_archive),
                *zip(runtime.dependency_archive_paths, dependencies, strict=True),
            ):
                _copy_runtime_file(source, target, deadline)
            _check_deadline(deadline)
            password = secrets.token_hex(15)  # 120 random bits, 30 UTF-8 bytes (< 32).
            main = workspace / "openttd.cfg"
            private = workspace / "private.cfg"
            secret = workspace / "secrets.cfg"
            game_creation = "".join(f"{key} = {value}\n" for key, value in scenario.items())
            _write_owned(
                main,
                "[version]\nversion_string = 13.4\nini_version = 2\n"
                "[game_creation]\n" + game_creation + "[network]\n"
                f"server_port = {lease.game_port}\nserver_admin_port = {lease.admin_port}\n"
                "server_game_type = local\nmin_active_clients = 0\n"
                "restart_game_year = 0\nreload_cfg = false\n"
                "[gui]\nautosave = monthly\nkeep_all_autosave = true\n"
                "threaded_saves = false\npause_on_newgame = true\n"
                "autosave_on_exit = false\n"
                "[ai]\nai_in_multiplayer = true\n"
                f"[ai_players]\n{ai_line}\n",
            )
            _write_owned(private, "[server_bind_addresses]\n127.0.0.1\n")
            _write_owned(secret, f"[network]\nadmin_password = {password}\n")
            _check_deadline(deadline)
            argv = (
                str(runtime.executable_path),
                f"-D127.0.0.1:{lease.game_port}",
                "-g",
                "-G",
                str(config.seed),
                "-I",
                "OpenGFX",
                "-c",
                str(main),
                "-x",
                "-X",
            )
            return PreparedLiveRuntime(
                runtime=runtime,
                workspace=workspace,
                main_config_path=main,
                private_config_path=private,
                secrets_config_path=secret,
                ai_archive_path=ai_archive,
                dependency_archive_paths=dependencies,
                graphics_archive_path=graphics,
                final_save_path=final_save,
                admin_password=password,
                lease=lease,
                argv=argv,
                provenance={
                    "execution_mode": "live",
                    "config_schema": "openttd-13.4-ini-v2",
                    "runtime": runtime.provenance,
                    "strategy_identifier": config.planning.strategy_identifier,
                    "strategy_version": config.planning.strategy_version,
                    "ai_content_id": config.ai.content_id,
                    "ai_md5": config.ai.md5,
                    "ai_parameters": dict(config.ai.parameters),
                    "seed": config.seed,
                    "game_port": lease.game_port,
                    "admin_port": lease.admin_port,
                    "bind_address": "127.0.0.1",
                    "server_game_type": "local",
                    "autosave": "monthly",
                    "final_save_name": save_name,
                },
            )
        except BaseException as exc:
            cleanup_failed = False
            if workspace is not None:
                try:
                    shutil.rmtree(workspace)
                except OSError:
                    cleanup_failed = True
            try:
                lease.close()
            except LiveLaunchError:
                cleanup_failed = True
            if cleanup_failed:
                raise LiveLaunchError(LiveLaunchCode.CLEANUP_FAILURE) from None
            if isinstance(exc, LiveLaunchError):
                raise
            if not isinstance(exc, Exception):
                raise
            if isinstance(exc, PermissionError):
                raise LiveLaunchError(LiveLaunchCode.PERMISSION_FAILURE) from None
            if workspace is None:
                raise LiveLaunchError(LiveLaunchCode.WORKSPACE_FAILURE) from None
            raise LiveLaunchError(LiveLaunchCode.SECRET_FAILURE) from None

    def _lease(
        self, game_port: int | None, admin_port: int | None, deadline: float | None = None
    ) -> PortLease:
        low, high = self.port_range
        if (
            type(low) is not int
            or type(high) is not int
            or not 1 <= low < high <= 65535
            or any(
                port is not None and (type(port) is not int or not 1 <= port <= 65535)
                for port in (game_port, admin_port)
            )
            or (game_port is not None and game_port == admin_port)
        ):
            raise LiveLaunchError(LiveLaunchCode.INVALID_PORT)
        try:
            self.lock_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            root_stat = self.lock_root.lstat()
            if (
                not stat.S_ISDIR(root_stat.st_mode)
                or root_stat.st_uid != os.getuid()
                or stat.S_IMODE(root_stat.st_mode) != 0o700
            ):
                raise LiveLaunchError(LiveLaunchCode.PERMISSION_FAILURE)
        except OSError:
            raise LiveLaunchError(LiveLaunchCode.PERMISSION_FAILURE) from None
        games = (game_port,) if game_port is not None else range(low, high + 1)
        admins = (admin_port,) if admin_port is not None else range(low, high + 1)
        saw_lease_conflict = False
        for game in games:
            for admin in admins:
                _check_deadline(deadline)
                if game == admin:
                    continue
                locks: list[IO[bytes]] = []
                claimed = False
                try:
                    for port in sorted((game, admin)):
                        descriptor = os.open(
                            self.lock_root / f"{port}.lock",
                            os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW,
                            0o600,
                        )
                        lock: IO[bytes] = os.fdopen(descriptor, "r+b")
                        locks.append(lock)
                        lock_stat = os.fstat(lock.fileno())
                        if (
                            not stat.S_ISREG(lock_stat.st_mode)
                            or lock_stat.st_uid != os.getuid()
                            or stat.S_IMODE(lock_stat.st_mode) != 0o600
                        ):
                            raise LiveLaunchError(LiveLaunchCode.PERMISSION_FAILURE)
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    if not (
                        _available(game, udp=False)
                        and _available(game, udp=True)
                        and _available(admin, udp=False)
                    ):
                        continue
                    claimed = True
                    return PortLease(game, admin, tuple(locks))
                except BlockingIOError:
                    saw_lease_conflict = True
                except OSError:
                    raise LiveLaunchError(LiveLaunchCode.PERMISSION_FAILURE) from None
                finally:
                    if not claimed:
                        for lock in reversed(locks):
                            lock.close()
        raise LiveLaunchError(
            LiveLaunchCode.LEASE_CONFLICT if saw_lease_conflict else LiveLaunchCode.PORT_IN_USE
        )
