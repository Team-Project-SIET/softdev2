"""Durable, credential-free evidence for one live terminal outcome.

The record describes the intended execution outcome. Database reconciliation is a
separate operation; this module neither reads history nor replays a run.
"""

import errno
import hashlib
import json
import os
import re
import secrets
import stat
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_serializer, model_validator

from app.experiments.domain import (
    ExecutionFailureCode,
    ExecutionMode,
    ExperimentConfig,
    LiveExecutionSummary,
    RunStatus,
    SimulationResult,
)
from app.experiments.plan_evaluation import PlanProvenance


class TerminalPersistence(StrEnum):
    """The manifest is published before the terminal transaction is attempted."""

    UNCONFIRMED = "unconfirmed"


class OutcomeManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    @model_serializer(mode="wrap")
    def serialize(self, handler):
        result = handler(self)
        if self.plan_provenance is None:
            result.pop("plan_provenance", None)
        return result

    schema_version: int = Field(default=1, ge=1, le=1)
    run_id: int = Field(gt=0)
    execution_mode: ExecutionMode = ExecutionMode.LIVE
    intended_status: RunStatus
    recorded_at: AwareDatetime
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    terminal_persistence: TerminalPersistence = TerminalPersistence.UNCONFIRMED
    simulation: SimulationResult | None = None
    failure_code: ExecutionFailureCode | None = None
    failure_message: str | None = None
    partial_artifact_reference: str | None = None
    partial_artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    final_artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    live_summary: LiveExecutionSummary | None = None
    plan_provenance: PlanProvenance | None = None

    @model_validator(mode="after")
    def validate_evidence(self) -> OutcomeManifest:
        if self.execution_mode is not ExecutionMode.LIVE:
            raise ValueError("outcome manifest requires live mode")
        if self.intended_status is RunStatus.SUCCEEDED:
            if self.simulation is None or self.failure_code is not None:
                raise ValueError("successful outcome requires only a simulation")
            if (
                self.live_summary is None
                or self.live_summary.raw_save_reference is None
                or self.live_summary.parsed_artifact_reference is None
                or self.simulation.raw_artifact_reference
                != self.live_summary.parsed_artifact_reference
            ):
                raise ValueError("successful outcome requires final artifact evidence")
        elif self.intended_status is RunStatus.FAILED:
            if self.simulation is not None:
                raise ValueError("failed outcome cannot contain a final simulation")
        else:
            raise ValueError("outcome manifest requires a terminal status")
        if self.failure_message is not None and self.failure_message not in {
            "live integration failure",
            "persistence failure",
            *(code.value.replace("_", " ") for code in ExecutionFailureCode),
        }:
            raise ValueError("outcome manifest message is not sanitized")
        if self.simulation is not None:
            for metric in self.simulation.metrics:
                if not re.fullmatch(r"[a-z][a-z0-9_]*", metric.name) or not re.fullmatch(
                    r"[A-Za-z0-9_/%-]+", metric.unit
                ):
                    raise ValueError("outcome manifest metric is not sanitized")
        if self.live_summary is not None:
            if self.live_summary.outcome_manifest_reference is not None:
                raise ValueError("outcome manifest cannot refer to itself")
            if any(
                re.fullmatch(r"[a-z0-9_]{1,80}", diagnostic) is None
                for diagnostic in self.live_summary.cleanup_diagnostics
            ):
                raise ValueError("outcome manifest diagnostic is not sanitized")
            for digest in (
                self.live_summary.raw_save_sha256,
                self.live_summary.parsed_artifact_sha256,
            ):
                if digest is not None and re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                    raise ValueError("outcome manifest digest is invalid")
        return self


def config_digest(config: ExperimentConfig) -> str:
    canonical = json.dumps(config.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def manifest_reference(run_id: int) -> str:
    return f"run-{run_id}/outcome-v1.json"


def _validate_reference(reference: str, run_dir: Path) -> Path:
    if not reference or "://" in reference or any(ord(char) < 32 for char in reference):
        raise ValueError("outcome manifest reference is not sanitized")
    if any(marker in reference.lower() for marker in ("password=", "secret=", "token=")):
        raise ValueError("outcome manifest reference is not sanitized")
    path = Path(reference)
    if path.is_absolute():
        raise ValueError("outcome manifest reference must be relative")
    candidate = run_dir.parent / path
    if candidate.parent != run_dir or candidate.name in {"", ".", ".."}:
        raise ValueError("outcome manifest artifact leaves owned run directory")
    return candidate


def _sha256(directory_fd: int, name: str) -> str:
    digest = hashlib.sha256()
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ValueError("outcome manifest artifact is a symlink") from None
        raise
    with os.fdopen(descriptor, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError("outcome manifest artifact is not a regular file")
        for block in iter(lambda: source.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _open_directory_chain(path: Path) -> int:
    """Anchor every root component without following an intermediate symlink."""
    current_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:]:
            try:
                next_fd = os.open(
                    component,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=current_fd,
                )
            except OSError as exc:
                if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                    raise ValueError("outcome manifest root contains a symlink") from None
                raise
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def publish_manifest(artifact_root: Path, manifest: OutcomeManifest) -> str:
    """Publish complete bytes once; a conflicting existing record is never replaced."""
    absolute_root = artifact_root.absolute()
    run_dir = absolute_root / f"run-{manifest.run_id}"
    root_fd = _open_directory_chain(absolute_root)
    try:
        directory_fd = os.open(
            run_dir.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd
        )
        try:
            manifest = _publish_in_directory(directory_fd, run_dir, manifest)
        finally:
            os.close(directory_fd)
    finally:
        os.close(root_fd)
    return manifest_reference(manifest.run_id)


def _publish_in_directory(
    directory_fd: int, run_dir: Path, manifest: OutcomeManifest
) -> OutcomeManifest:
    if manifest.plan_provenance is not None:
        for field in (
            "input_artifact",
            "receipt",
            "realized",
            "comparison",
            "evaluation",
            "telemetry",
            "runtime",
        ):
            ref = getattr(manifest.plan_provenance, field)
            if ref is not None:
                path = _validate_reference(f"run-{manifest.run_id}/{ref.reference}", run_dir)
                if _sha256(directory_fd, path.name) != ref.sha256:
                    raise ValueError("plan artifact identity mismatch")
    if manifest.partial_artifact_reference is not None:
        partial = _validate_reference(manifest.partial_artifact_reference, run_dir)
        manifest = manifest.model_copy(
            update={"partial_artifact_sha256": _sha256(directory_fd, partial.name)}
        )
    if manifest.simulation is not None and manifest.simulation.raw_artifact_reference is not None:
        final = _validate_reference(manifest.simulation.raw_artifact_reference, run_dir)
        manifest = manifest.model_copy(
            update={"final_artifact_sha256": _sha256(directory_fd, final.name)}
        )
    if manifest.live_summary is not None:
        updates: dict[str, str] = {}
        for reference, expected_digest, digest_field in (
            (
                manifest.live_summary.raw_save_reference,
                manifest.live_summary.raw_save_sha256,
                "raw_save_sha256",
            ),
            (
                manifest.live_summary.parsed_artifact_reference,
                manifest.live_summary.parsed_artifact_sha256,
                "parsed_artifact_sha256",
            ),
        ):
            if reference is not None:
                artifact = _validate_reference(reference, run_dir)
                actual_digest = _sha256(directory_fd, artifact.name)
                if expected_digest is not None and actual_digest != expected_digest:
                    raise ValueError("outcome manifest artifact digest mismatch")
                updates[digest_field] = actual_digest
        if updates:
            manifest = manifest.model_copy(
                update={"live_summary": manifest.live_summary.model_copy(update=updates)}
            )
    data = (manifest.model_dump_json() + "\n").encode("utf-8")
    temporary = f".outcome-v1-{secrets.token_hex(16)}.tmp"
    fd = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory_fd,
    )
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(
                temporary,
                "outcome-v1.json",
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            try:
                existing_fd = os.open(
                    "outcome-v1.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd
                )
                with os.fdopen(existing_fd, "rb") as existing:
                    identical = stat.S_ISREG(os.fstat(existing.fileno()).st_mode) and (
                        existing.read() == data
                    )
            except OSError:
                identical = False
            if not identical:
                raise FileExistsError("conflicting outcome manifest") from None
        os.fsync(directory_fd)
    finally:
        os.unlink(temporary, dir_fd=directory_fd)
    return manifest


def new_manifest(
    config: ExperimentConfig,
    run_id: int,
    *,
    simulation: SimulationResult | None = None,
    failure_code: ExecutionFailureCode | None = None,
    failure_message: str | None = None,
    partial_artifact_reference: str | None = None,
    live_summary: LiveExecutionSummary | None = None,
    plan_provenance: PlanProvenance | None = None,
) -> OutcomeManifest:
    return OutcomeManifest(
        run_id=run_id,
        intended_status=RunStatus.SUCCEEDED if simulation is not None else RunStatus.FAILED,
        recorded_at=datetime.now(UTC),
        config_sha256=config_digest(config),
        simulation=(
            simulation.model_copy(update={"live_summary": None}) if simulation is not None else None
        ),
        failure_code=failure_code,
        failure_message=failure_message,
        partial_artifact_reference=partial_artifact_reference,
        live_summary=live_summary,
        plan_provenance=plan_provenance,
    )
