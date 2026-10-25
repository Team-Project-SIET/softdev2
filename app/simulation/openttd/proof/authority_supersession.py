"""Explicit, fail-closed supersession of a single historical authority pin.

The retained historical manifests are immutable evidence. When a pinned file has
legitimately advanced and its historical bytes are not retained, a separate
operator-authorized record may scope a byte-exact transition for that one path.
Every other protected entry is still validated by the unmodified
``validate_protection`` contract.
"""

import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

from app.simulation.openttd.proof.historical_protection import (
    protection_digest,
    validate_protection,
)

POLICY = "context-authority-supersession-v1"
DEFAULT_RECORD = Path("docs/authority/context-authority-supersession.json")
REQUIRED_KEYS = {
    "policy",
    "path",
    "historical_sha256",
    "historical_bytes_retained",
    "current_sha256",
    "recorded",
    "authority",
    "decision",
    "reason",
}
_HEX = frozenset("0123456789abcdef")


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _is_digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX


def load_record(project: Path, record_path: Path = DEFAULT_RECORD) -> dict[str, Any]:
    """Load and structurally validate the supersession record."""
    path = project / record_path
    record = json.loads(path.read_bytes())
    if not isinstance(record, dict) or set(record) != REQUIRED_KEYS:
        raise ValueError("Authority supersession record shape invalid")
    if record["policy"] != POLICY:
        raise ValueError("Authority supersession policy mismatch")
    target = record["path"]
    if not isinstance(target, str):
        raise ValueError("Authority supersession path invalid")
    pure = PurePosixPath(target)
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != target or not pure.parts:
        raise ValueError("Authority supersession path unsafe")
    if not _is_digest(record["historical_sha256"]) or not _is_digest(record["current_sha256"]):
        raise ValueError("Authority supersession digest invalid")
    if record["historical_sha256"] == record["current_sha256"]:
        raise ValueError("Authority supersession is a no-op")
    if record["historical_bytes_retained"] is not False:
        raise ValueError("Authority supersession must state retained historical bytes")
    for key in ("recorded", "authority", "decision", "reason"):
        if not isinstance(record[key], str) or not record[key].strip():
            raise ValueError(f"Authority supersession {key} missing")
    return record


def current_pin(project: Path, record: dict[str, Any]) -> str:
    """Return the live byte identity only when it matches the recorded transition."""
    target = project / record["path"]
    if target.is_symlink() or not target.is_file():
        raise ValueError("Authority supersession target missing or substituted")
    live = _digest(target.read_bytes())
    if live != record["current_sha256"]:
        raise ValueError("Authority supersession current bytes changed")
    return live


def resolve_historical_pin(
    project: Path, historical_sha256: str, record_path: Path = DEFAULT_RECORD
) -> str:
    """Resolve one historical pin to the recorded current identity, or refuse.

    This never claims the historical bytes are available; it only proves that the
    historical identity is exactly the one the record supersedes and that the live
    file is the recorded successor.
    """
    record = load_record(project, record_path)
    if historical_sha256 != record["historical_sha256"]:
        raise ValueError("Authority supersession does not bind this historical pin")
    return current_pin(project, record)


def validate_protection_with_supersession(
    project: Path, manifest: dict[str, Any], record_path: Path = DEFAULT_RECORD
) -> int:
    """Validate a frozen protection manifest with exactly one recorded transition.

    The original manifest self-digest is verified before any transformation, so
    the frozen evidence must be byte-consistent. Only the recorded path may take
    the recorded successor bytes; all other entries remain exact.
    """
    record = load_record(project, record_path)
    if manifest.get("sha256") != protection_digest(manifest):
        raise ValueError("Historical manifest digest mismatch")
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise ValueError("Historical manifest entries invalid")
    rows = [entry for entry in entries if entry.get("path") == record["path"]]
    if len(rows) != 1 or rows[0].get("sha256") != record["historical_sha256"]:
        raise ValueError("Authority supersession does not bind this manifest")
    successor = current_pin(project, record)
    patched = copy.deepcopy(manifest)
    for entry in patched["entries"]:
        if entry["path"] == record["path"]:
            entry["sha256"] = successor
            break
    patched["sha256"] = protection_digest(patched)
    return validate_protection(project, patched)
