"""Owned config-relative 15.3 directories; never use the user's profile."""

import ipaddress
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .ownership import OwnershipGraph


@dataclass(frozen=True)
class AdminSettings:
    password: str = field(repr=False)
    bind_address: str = "127.0.0.1"
    port: int = 3977
    game_port: int = 3979
    authorized_public_key_hex: str | None = None

    def __post_init__(self) -> None:
        if self.authorized_public_key_hex is not None and not re.fullmatch(
            r"[0-9a-f]{64}", self.authorized_public_key_hex
        ):
            raise ValueError("Authorized key must be 32 bytes of lowercase hexadecimal")
        if (
            self.bind_address != "127.0.0.1"
            or not ipaddress.ip_address(self.bind_address).is_loopback
        ):
            raise ValueError("Controlled runtime requires IPv4 loopback")
        if not (0 < self.port < 65536 and 0 < self.game_port < 65536):
            raise ValueError("Invalid port")
        if self.port == self.game_port:
            raise ValueError("Admin and game ports must differ")
        if (
            (not self.password and self.authorized_public_key_hex is None)
            or len(self.password.encode()) > 32
            or any(
                char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
                for char in self.password
            )
        ):
            raise ValueError("Password must be 1-32 safe ASCII bytes")


@dataclass(frozen=True)
class RuntimeWorkspace:
    _temporary: tempfile.TemporaryDirectory[str] | None = field(repr=False, compare=False)
    root: Path

    @classmethod
    def create(cls, parent: Path, *, retain: bool = False) -> RuntimeWorkspace:
        parent = parent.expanduser().resolve()
        for profile in (Path.home() / ".config/openttd", Path.home() / ".local/share/openttd"):
            if parent.is_relative_to(profile.resolve()):
                raise ValueError("Workspace must not be inside the user's OpenTTD profile")
        parent.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(
            prefix="openttd-15.3-", dir=parent, delete=not retain
        )
        workspace = cls(temporary, Path(temporary.name))
        try:
            for relative in (
                "save/autosave",
                "logs",
                "game/library",
                "ai/library",
                "baseset",
                "artifacts",
                "home",
                "xdg/config",
                "xdg/data",
                "xdg/cache",
                "scripts",
            ):
                (workspace.root / relative).mkdir(parents=True, exist_ok=True)
        except BaseException:
            temporary.cleanup()
            raise
        (workspace.root / ".runtime-owned").write_text("OpenTTD 15.3 isolated runtime\n")
        return workspace

    @classmethod
    def reopen(cls, root: Path) -> RuntimeWorkspace:
        root = root.resolve(strict=True)
        for profile in (Path.home() / ".config/openttd", Path.home() / ".local/share/openttd"):
            if root.is_relative_to(profile.resolve()):
                raise ValueError("Normal profile forbidden")
        if not (root / ".runtime-owned").is_file() or root.stat().st_mode & 0o077:
            raise ValueError("Not a restricted owned runtime workspace")
        return cls(None, root)

    @property
    def config(self) -> Path:
        return self.root / "openttd.cfg"

    @property
    def save(self) -> Path:
        return self.root / "save"

    @property
    def autosave(self) -> Path:
        return self.save / "autosave"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def game(self) -> Path:
        return self.root / "game"

    @property
    def ai(self) -> Path:
        return self.root / "ai"

    def close(self, *, ownership: OwnershipGraph | None = None) -> None:
        """Reap first; reject aliases and persistent paths before recursive disposal."""
        if not self.root.exists():
            return
        if self.root.absolute() != self.root.resolve() or self.root.is_symlink():
            raise ValueError("Aliasing cleanup root")
        if not (self.root / ".runtime-owned").is_file():
            raise ValueError("Missing workspace ownership marker")
        if any(p.is_symlink() for p in self.root.rglob("*")):
            raise ValueError("Workspace symlink crosses cleanup ownership boundary")
        if ownership is not None:
            ownership.validate()
            if ownership.cleanup_roots != (self.root,):
                raise ValueError("Cleanup root differs from frozen ownership")
        # Retain only controls preparation's temporary finalizer. Explicit close
        # always disposes the owned tree, consistently after reopen or in-process.
        shutil.rmtree(self.root)

    def write_config(self, admin: AdminSettings) -> None:
        files = {
            "openttd.cfg": (
                "[version]\nversion_string = 15.3\nini_version = 7\n"
                "[network]\n"
                f"server_port = {admin.game_port}\nserver_admin_port = {admin.port}\n"
                "server_game_type = local\nmin_active_clients = 0\n"
                "reload_cfg = false\nallow_insecure_admin_login = false\n"
                "[gui]\nautosave_interval = 0\nautosave_on_exit = false\n"
                "threaded_saves = false\npause_on_newgame = true\n"
            ),
            "private.cfg": "[version]\nini_version = 7\n[server_bind_addresses]\n127.0.0.1\n",
            "secrets.cfg": "[version]\nini_version = 7\n[network]\n"
            f"admin_password = {admin.password}\n",
        }
        if admin.authorized_public_key_hex is not None:
            files["private.cfg"] += f"[admin_authorized_keys]\n{admin.authorized_public_key_hex}\n"
        for name, text in files.items():
            path = self.root / name
            # Exclusive creation prevents symlink following and accidental overwrite.
            with path.open("x") as stream:
                path.chmod(0o600)
                stream.write(text)

    @property
    def environment(self) -> tuple[tuple[str, str], ...]:
        """Overrides to merge with the parent's environment at a future authorized launch."""
        return tuple(
            (name, str(self.root / relative))
            for name, relative in (
                ("HOME", "home"),
                ("XDG_CONFIG_HOME", "xdg/config"),
                ("XDG_DATA_HOME", "xdg/data"),
                ("XDG_CACHE_HOME", "xdg/cache"),
            )
        )
