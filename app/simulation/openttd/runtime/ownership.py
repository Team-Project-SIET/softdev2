"""Resolved path ownership, independent of proof kind or runtime execution."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class PathClass(StrEnum):
    IMMUTABLE_SOURCE = "IMMUTABLE_SOURCE"
    PROTECTED_HISTORICAL = "PROTECTED_HISTORICAL"
    RUNTIME_EPHEMERAL = "RUNTIME_EPHEMERAL"
    RUNTIME_CREDENTIAL = "RUNTIME_CREDENTIAL"
    GENERATED_EVIDENCE = "GENERATED_EVIDENCE"


PERSISTENT = frozenset(
    (PathClass.IMMUTABLE_SOURCE, PathClass.PROTECTED_HISTORICAL, PathClass.GENERATED_EVIDENCE)
)


@dataclass(frozen=True)
class PathOwnership:
    path: Path
    kind: PathClass


@dataclass(frozen=True)
class OwnershipGraph:
    cleanup_roots: tuple[Path, ...]
    entries: tuple[PathOwnership, ...]

    def validate(self) -> None:
        roots = []
        for root in self.cleanup_roots:
            if root.absolute() != root.resolve() or root.is_symlink():
                raise ValueError("Aliasing cleanup root")
            if any(root == r or root.is_relative_to(r) or r.is_relative_to(root) for r in roots):
                raise ValueError("Overlapping cleanup roots")
            roots.append(root)
        seen = set()
        persistent_inodes = set()
        ephemeral_inodes = set()
        for entry in self.entries:
            path = entry.path
            resolved = path.resolve()
            if resolved in seen:
                raise ValueError("Duplicate or ambiguous path ownership")
            seen.add(resolved)
            if path.absolute() != resolved or path.is_symlink():
                raise ValueError("Path alias/symlink ownership ambiguity")
            owned = any(resolved == root or resolved.is_relative_to(root) for root in roots)
            if entry.kind in PERSISTENT and owned:
                raise ValueError("Persistent path intersects cleanup root")
            if entry.kind not in PERSISTENT and not owned:
                raise ValueError("Cleanup-owned path outside cleanup root")
            if path.is_file():
                info = path.stat()
                inode = (info.st_dev, info.st_ino)
                (persistent_inodes if entry.kind in PERSISTENT else ephemeral_inodes).add(inode)
        if persistent_inodes & ephemeral_inodes:
            raise ValueError("Hardlink alias across ownership boundary")

    def public(self) -> dict:
        self.validate()
        return dict(
            policy="resolved-path-ownership-v1",
            cleanup_roots=[str(p) for p in self.cleanup_roots],
            entries=[
                dict(path=str(e.path), kind=e.kind.value)
                for e in sorted(self.entries, key=lambda e: str(e.path))
            ],
        )

    @classmethod
    def from_public(cls, value: dict):
        if value.get("policy") != "resolved-path-ownership-v1":
            raise ValueError("Ownership policy mismatch")
        graph = cls(
            tuple(Path(p) for p in value["cleanup_roots"]),
            tuple(PathOwnership(Path(e["path"]), PathClass(e["kind"])) for e in value["entries"]),
        )
        graph.validate()
        return graph
