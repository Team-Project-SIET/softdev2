"""T14 local outcome evidence; no recovery reader is involved."""

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_experiments import baseline_config

from app.experiments.domain import (
    ExecutionFailureCode,
    LiveExecutionSummary,
    Metric,
    SimulationResult,
    TelemetryStatus,
)
from app.experiments.outcome_manifest import OutcomeManifest, new_manifest, publish_manifest


def _run_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "run-1"
    directory.mkdir()
    return directory


def test_success_manifest_is_typed_deterministic_and_durable(tmp_path: Path) -> None:
    directory = _run_dir(tmp_path)
    (directory / "final.json.gz").write_bytes(b"controlled parsed artifact")
    (directory / "final.sav").write_bytes(b"controlled raw save")
    summary = LiveExecutionSummary(
        telemetry_status=TelemetryStatus.INCOMPLETE,
        raw_save_reference="run-1/final.sav",
        parsed_artifact_reference="run-1/final.json.gz",
    )
    simulation = SimulationResult(
        simulation_date=date(1950, 1, 2),
        savegame_version=302,
        metrics=(Metric(name="company_money", value=42, unit="GBP"),),
        raw_artifact_reference="run-1/final.json.gz",
        live_summary=summary,
    )
    manifest = new_manifest(baseline_config(), 1, simulation=simulation, live_summary=summary)
    reference = publish_manifest(directory.parent, manifest)
    target = directory / "outcome-v1.json"
    assert reference == "run-1/outcome-v1.json"
    assert (
        json.loads(target.read_text())["final_artifact_sha256"]
        == hashlib.sha256(b"controlled parsed artifact").hexdigest()
    )
    assert publish_manifest(directory.parent, manifest) == reference
    document = json.loads(target.read_text())
    assert document["schema_version"] == 1
    assert document["execution_mode"] == "live"
    assert document["intended_status"] == "succeeded"
    assert document["terminal_persistence"] == "unconfirmed"
    assert document["simulation"]["metrics"] == [
        {"name": "company_money", "value": 42.0, "unit": "GBP"}
    ]
    assert len(document["config_sha256"]) == 64
    assert not list(directory.glob("*.tmp"))


def test_failed_manifest_retains_code_and_partial_only(tmp_path: Path) -> None:
    directory = _run_dir(tmp_path)
    (directory / "partial.sav").write_bytes(b"controlled partial")
    manifest = new_manifest(
        baseline_config(),
        1,
        failure_code=ExecutionFailureCode.TIMEOUT,
        failure_message="timeout",
        partial_artifact_reference="run-1/partial.sav",
        live_summary=LiveExecutionSummary(
            telemetry_status=TelemetryStatus.FAILED,
            cleanup_succeeded=True,
            cleanup_diagnostics=("owned_process_term_error",),
        ),
    )
    publish_manifest(directory.parent, manifest)
    document = json.loads((directory / "outcome-v1.json").read_text())
    assert document["intended_status"] == "failed"
    assert document["failure_code"] == "timeout"
    assert document["partial_artifact_reference"] == "run-1/partial.sav"
    assert document["partial_artifact_sha256"] == hashlib.sha256(b"controlled partial").hexdigest()
    assert document["simulation"] is None
    assert document["live_summary"]["cleanup_diagnostics"] == ["owned_process_term_error"]


def test_success_manifest_requires_bound_final_artifacts() -> None:
    simulation = SimulationResult(
        simulation_date=date(1950, 1, 2),
        savegame_version=302,
        metrics=(),
    )
    with pytest.raises(ValidationError, match="final artifact evidence"):
        new_manifest(baseline_config(), 1, simulation=simulation)


@pytest.mark.parametrize(
    "reference",
    [
        "../outside.sav",
        "run-2/other.sav",
        "/tmp/run-1/absolute.sav",
        "postgresql://user:password@host/db",
        "run-1/x\nsecret",
    ],
)
def test_manifest_rejects_unsafe_reference(tmp_path: Path, reference: str) -> None:
    directory = _run_dir(tmp_path)
    manifest = new_manifest(
        baseline_config(),
        1,
        failure_code=ExecutionFailureCode.TIMEOUT,
        partial_artifact_reference=reference,
    )
    with pytest.raises(ValueError):
        publish_manifest(directory.parent, manifest)
    assert not (directory / "outcome-v1.json").exists()


def test_manifest_rejects_symlink_escape_and_conflicting_outcome(tmp_path: Path) -> None:
    directory = _run_dir(tmp_path)
    (directory / "external.sav").symlink_to(tmp_path / "outside.sav")
    unsafe = new_manifest(
        baseline_config(),
        1,
        failure_code=ExecutionFailureCode.TIMEOUT,
        partial_artifact_reference="run-1/external.sav",
    )
    with pytest.raises(ValueError):
        publish_manifest(directory.parent, unsafe)
    first = new_manifest(baseline_config(), 1, failure_code=ExecutionFailureCode.TIMEOUT)
    publish_manifest(directory.parent, first)
    with pytest.raises(FileExistsError):
        publish_manifest(
            directory.parent,
            new_manifest(baseline_config(), 1, failure_code=ExecutionFailureCode.CANCELLED),
        )


def test_manifest_rejects_symlink_in_artifact_root_ancestry(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    (actual / "run-1").mkdir(parents=True)
    (tmp_path / "alias").symlink_to(actual, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        publish_manifest(
            tmp_path / "alias",
            new_manifest(baseline_config(), 1, failure_code=ExecutionFailureCode.TIMEOUT),
        )
    intermediate = tmp_path / "intermediate"
    intermediate.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        publish_manifest(
            intermediate / "actual",
            new_manifest(baseline_config(), 1, failure_code=ExecutionFailureCode.TIMEOUT),
        )


def test_manifest_write_failure_never_publishes_partial_final(tmp_path: Path, monkeypatch) -> None:
    from app.experiments import outcome_manifest

    directory = _run_dir(tmp_path)
    manifest = new_manifest(baseline_config(), 1, failure_code=ExecutionFailureCode.TIMEOUT)

    def fail_link(source, target, *, src_dir_fd, dst_dir_fd, follow_symlinks):
        raise OSError("controlled publication failure")

    monkeypatch.setattr(outcome_manifest.os, "link", fail_link)
    with pytest.raises(OSError, match="publication failure"):
        publish_manifest(directory.parent, manifest)
    assert list(directory.iterdir()) == []


def test_manifest_file_fsync_failure_leaves_no_final(tmp_path: Path, monkeypatch) -> None:
    from app.experiments import outcome_manifest

    directory = _run_dir(tmp_path)
    manifest = new_manifest(baseline_config(), 1, failure_code=ExecutionFailureCode.TIMEOUT)

    def fail_fsync(descriptor: int) -> None:
        raise OSError("controlled sync failure")

    monkeypatch.setattr(outcome_manifest.os, "fsync", fail_fsync)
    with pytest.raises(OSError, match="sync failure"):
        publish_manifest(directory.parent, manifest)
    assert list(directory.iterdir()) == []


def test_manifest_rejects_existing_artifact_with_wrong_digest(tmp_path: Path) -> None:
    directory = _run_dir(tmp_path)
    (directory / "final.sav").write_bytes(b"controlled save")
    manifest = new_manifest(
        baseline_config(),
        1,
        failure_code=ExecutionFailureCode.TIMEOUT,
        live_summary=LiveExecutionSummary(
            telemetry_status=TelemetryStatus.FAILED,
            raw_save_reference="run-1/final.sav",
            raw_save_sha256="0" * 64,
        ),
    )
    with pytest.raises(ValueError, match="digest mismatch"):
        publish_manifest(directory.parent, manifest)
    assert not (directory / "outcome-v1.json").exists()


@pytest.mark.parametrize(
    "unsafe",
    [
        "DATABASE_URL=postgresql://user:password@host/db",
        "argv: --password=secret",
        "Traceback (most recent call last):",
        "raw stdout secret",
    ],
)
def test_manifest_rejects_unbounded_terminal_messages(unsafe: str) -> None:
    with pytest.raises(ValidationError, match="not sanitized"):
        new_manifest(
            baseline_config(),
            1,
            failure_code=ExecutionFailureCode.TIMEOUT,
            failure_message=unsafe,
        )


def test_manifest_contract_rejects_arbitrary_fields_and_raw_cleanup() -> None:
    manifest = new_manifest(baseline_config(), 1, failure_code=ExecutionFailureCode.TIMEOUT)
    with pytest.raises(ValidationError):
        OutcomeManifest.model_validate({**manifest.model_dump(), "environment": {"SECRET": "x"}})
    with pytest.raises(ValidationError, match="not sanitized"):
        new_manifest(
            baseline_config(),
            1,
            failure_code=ExecutionFailureCode.TIMEOUT,
            live_summary=LiveExecutionSummary(
                telemetry_status=TelemetryStatus.FAILED,
                cleanup_diagnostics=("password=secret",),
            ),
        )
