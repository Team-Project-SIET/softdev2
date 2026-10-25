"""Fail-closed checks for the explicit CONTEXT.md authority-pin supersession."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from app.simulation.openttd.proof.authority_supersession import (
    current_pin,
    load_record,
    resolve_historical_pin,
    validate_protection_with_supersession,
)
from app.simulation.openttd.proof.historical_protection import validate_protection

PROJECT = Path(__file__).resolve().parents[1]
FREEZE = PROJECT / "artifacts/runtime/openttd-15.3-two-rollover-qualification-real-prelaunch-v4"


def _record(tmp_path: Path, historical: str, current_bytes: bytes, **overrides) -> Path:
    record = {
        "policy": "context-authority-supersession-v1",
        "path": "CONTEXT.md",
        "historical_sha256": historical,
        "historical_bytes_retained": False,
        "current_sha256": hashlib.sha256(current_bytes).hexdigest(),
        "recorded": "2026-10-25",
        "authority": "test authority",
        "decision": "ADR-014",
        "reason": "test reason",
    }
    record.update(overrides)
    (tmp_path / "CONTEXT.md").write_bytes(current_bytes)
    path = tmp_path / "docs/authority/context-authority-supersession.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(record))
    return path


def test_record_binds_exact_historical_and_current_identity():
    record = load_record(PROJECT)
    assert record["path"] == "CONTEXT.md"
    assert record["historical_sha256"] == (
        "b94b96649b466e73e25c9df9409bd745e311b84273bedfd9a111792869e3b7b3"
    )
    assert record["historical_bytes_retained"] is False
    assert record["current_sha256"] == hashlib.sha256(
        (PROJECT / "CONTEXT.md").read_bytes()
    ).hexdigest()


def test_frozen_manifest_validates_with_only_the_recorded_transition():
    manifest = json.loads((FREEZE / "historical-integrity.json").read_text())
    assert validate_protection_with_supersession(PROJECT, manifest) == 1627


def test_unmodified_validator_still_rejects_the_diverged_context():
    """The base contract is not weakened: only the explicit wrapper is scoped."""
    manifest = json.loads((FREEZE / "historical-integrity.json").read_text())
    with pytest.raises(ValueError, match="CONTEXT.md"):
        validate_protection(PROJECT, manifest)


def test_wrong_historical_pin_is_refused():
    with pytest.raises(ValueError, match="does not bind"):
        resolve_historical_pin(PROJECT, "0" * 64)


def test_live_drift_after_recording_is_refused(tmp_path):
    record_path = _record(tmp_path, "0" * 63 + "1", b"current authority\n")
    (tmp_path / "CONTEXT.md").write_bytes(b"drifted authority\n")
    with pytest.raises(ValueError, match="current bytes changed"):
        current_pin(tmp_path, load_record(tmp_path, record_path.relative_to(tmp_path)))


def test_record_claiming_retained_historical_bytes_is_refused(tmp_path):
    record_path = _record(
        tmp_path, "0" * 63 + "1", b"current authority\n", historical_bytes_retained=True
    )
    with pytest.raises(ValueError, match="retained historical bytes"):
        load_record(tmp_path, record_path.relative_to(tmp_path))


def test_manifest_with_a_different_historical_pin_is_refused():
    manifest = json.loads((FREEZE / "historical-integrity.json").read_text())
    wrong = copy.deepcopy(manifest)
    row = next(e for e in wrong["entries"] if e["path"] == "CONTEXT.md")
    row["sha256"] = "0" * 64
    from app.simulation.openttd.proof.historical_protection import protection_digest

    wrong["sha256"] = protection_digest(wrong)
    with pytest.raises(ValueError, match="does not bind"):
        validate_protection_with_supersession(PROJECT, wrong)


def test_manifest_tamper_outside_the_transition_still_fails():
    manifest = json.loads((FREEZE / "historical-integrity.json").read_text())
    tampered = copy.deepcopy(manifest)
    row = next(e for e in tampered["entries"] if e["path"] != "CONTEXT.md")
    row["sha256"] = "0" * 64
    from app.simulation.openttd.proof.historical_protection import protection_digest

    tampered["sha256"] = protection_digest(tampered)
    with pytest.raises(ValueError, match="protected hash changed"):
        validate_protection_with_supersession(PROJECT, tampered)
