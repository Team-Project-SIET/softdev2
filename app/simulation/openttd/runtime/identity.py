"""Semantic identity excludes workspace paths and process activity."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class RuntimeIdentity:
    executable: Path
    version: str
    sha256: str
    backend: Literal["external"] = "external"


@dataclass(frozen=True)
class VersionInspection:
    argv: tuple[str, ...]
    stdout: bytes
    stderr: bytes
    exit_code: int
