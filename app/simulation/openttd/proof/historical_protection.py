"""One captured path authority for historical evidence, with a fixed time boundary.

New sibling directories/files are not retroactive inputs. Within captured historical
roots the exact file set is immutable. Current preparation/attempt workspaces and
private credentials never enter this public manifest. Archived workspace inputs
in previous freezes remain historical evidence and are preserved.
"""

import hashlib
import json
from pathlib import Path, PurePosixPath

from app.simulation.openttd.admin_crypto import AuthorizedKey

POLICY = "historical-exact-paths-v1"


def protection_base(project: Path, runtime: Path) -> Path:
    """Keep isolated controlled preparations outside the repository self-contained."""
    return project if runtime.resolve().is_relative_to(project.resolve()) else runtime


def protection_digest(manifest: dict) -> str:
    value = {k: v for k, v in manifest.items() if k != "sha256"}
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _relative(project: Path, path: Path) -> str:
    return path.absolute().relative_to(project.absolute()).as_posix()


def _path(project: Path, name: str) -> Path:
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or p.as_posix() != name or not p.parts:
        raise ValueError("Historical unsafe path")
    path = project / name
    if path.is_symlink() or not path.resolve().is_relative_to(project.resolve()):
        raise ValueError("Historical path substitution")
    return path


def _enumerate(project: Path, roots: list[str], files: list[str]) -> list[str]:
    paths = set(files)
    for name in roots:
        root = _path(project, name)
        if not root.is_dir():
            raise ValueError(f"Historical root missing: {name}")
        for path in sorted(root.rglob("*")):
            if path.name == ".admin-secret":
                continue
            if path.is_symlink():
                raise ValueError("Historical symlink substitution")
            if path.is_file():
                paths.add(_relative(project, path))
    return sorted(paths)


def _credentials(project: Path, roots: list[str]) -> list[dict]:
    """Preserve the legacy public-key/mode check without publishing private hashes."""
    identities = []
    for root in roots:
        for path in sorted(_path(project, root).rglob(".admin-secret")):
            if path.is_symlink() or not path.is_file():
                raise ValueError("Historical credential substitution")
            identities.append(
                dict(
                    path=_relative(project, path),
                    public_key=AuthorizedKey.from_bytes(path.read_bytes()).public_hex,
                    mode=path.stat().st_mode & 0o777,
                )
            )
    return sorted(identities, key=lambda identity: identity["path"])


def capture_protection(project: Path, runtime: Path, current: Path, future: Path) -> dict:
    excluded = {_relative(project, p) for p in (current, future)}
    roots = sorted(
        _relative(project, p)
        for p in runtime.iterdir()
        if p.is_dir() and _relative(project, p) not in excluded
    )
    files = sorted(
        _relative(project, p)
        for p in runtime.iterdir()
        if p.is_file() and p.name != ".admin-secret"
    )
    if (project / "CONTEXT.md").is_file():
        files.append("CONTEXT.md")
    files = sorted(files)
    paths = _enumerate(project, roots, files)
    entries = [
        {"path": n, "sha256": hashlib.sha256(_path(project, n).read_bytes()).hexdigest()}
        for n in paths
    ]
    value = dict(
        policy=POLICY,
        roots=roots,
        explicit_files=files,
        excluded_roots=sorted(excluded),
        excluded_names=[".admin-secret"],
        boundary="captured roots and explicit files only; later siblings are not retroactive",
        paths=paths,
        entries=entries,
        unique_count=len(paths),
        credential_identities=_credentials(project, roots),
    )
    value["sha256"] = protection_digest(value)
    return value


def validate_protection(project: Path, manifest: dict) -> int:
    try:
        if manifest["policy"] != POLICY or manifest["excluded_names"] != [".admin-secret"]:
            raise ValueError("Historical policy mismatch")
        for key in ("roots", "explicit_files", "excluded_roots", "paths"):
            values = manifest[key]
            if values != sorted(set(values)):
                raise ValueError("Historical duplicate or unordered paths")
            for n in values:
                _path(project, n)
        paths = manifest["paths"]
        entries = manifest["entries"]
        if any(PurePosixPath(p).name == ".admin-secret" for p in paths):
            raise ValueError("Historical private credential in public manifest")
        for root in manifest["roots"]:
            if any(
                PurePosixPath(root).is_relative_to(PurePosixPath(excluded))
                for excluded in manifest["excluded_roots"]
            ):
                raise ValueError("Historical excluded workspace entered protected roots")
        if [e["path"] for e in entries] != paths or manifest["unique_count"] != len(paths):
            raise ValueError("Historical path/count accounting mismatch")
        if manifest["sha256"] != protection_digest(manifest):
            raise ValueError("Historical manifest digest mismatch")
        if _enumerate(project, manifest["roots"], manifest["explicit_files"]) != paths:
            raise ValueError("Historical protected path set changed")
        if _credentials(project, manifest["roots"]) != manifest["credential_identities"]:
            raise ValueError("Historical credential identity changed")
        for entry in entries:
            path = _path(project, entry["path"])
            if (
                not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]
            ):
                raise ValueError(f"Historical protected hash changed: {entry['path']}")
    except (KeyError, TypeError, OSError) as error:
        raise ValueError("Historical manifest invalid or protected input missing") from error
    return len(paths)
