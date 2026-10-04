"""Explicit reconciliation of a validated T14 live outcome into PostgreSQL."""

import errno
import gzip
import json
import os
import re
import stat
from collections.abc import Callable
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.session import create_session
from app.experiments.domain import (
    AIConfig,
    ExecutionFailureCode,
    ExecutionMode,
    ExperimentConfig,
    LiveExecutionSummary,
    Metric,
    PlanningConfiguration,
    RunStatus,
    ScenarioConfig,
    SimulationResult,
    TelemetryStatus,
)
from app.experiments.model import ExperimentRunRecord, LiveTelemetrySessionRecord
from app.experiments.outcome_manifest import (
    OutcomeManifest,
    _open_directory_chain,
    _sha256,
    _validate_reference,
    config_digest,
)
from app.experiments.plan_artifacts import final_save_values
from app.experiments.plan_evaluation import PlanEvaluationInput, accept_execution, realized_metrics
from app.experiments.plan_service import runtime_config
from app.experiments.repository import ExperimentRepository
from app.experiments.workspace_recovery import cleanup_abandoned_workspaces
from app.planning.canonical import canonical_bytes, plan_hash, scenario_hash, world_manifest_hash
from app.planning.execution_evidence import parse_execution_evidence
from app.planning.realized import RealizedSimulationMetrics, compare_metrics

MAX_MANIFEST_BYTES = 1024 * 1024


class RecoveryStatus(StrEnum):
    RECOVERED = "recovered"
    ALREADY_RECONCILED = "already_reconciled"
    INVALID_MANIFEST = "invalid_manifest"
    UNSUPPORTED_VERSION = "unsupported_version"
    CONFLICT = "conflict"
    FAILED = "failed"


class RecoveryResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: RecoveryStatus
    run_id: int | None = None
    reason: str | None = None
    workspace_cleanup_pending: bool = False


class _VersionProbe(BaseModel):
    schema_version: StrictInt


class _StrictMetric(Metric):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _StrictSimulation(SimulationResult):
    model_config = ConfigDict(frozen=True, extra="forbid")
    metrics: tuple[_StrictMetric, ...]


class _StrictSummary(LiveExecutionSummary):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _StrictManifest(OutcomeManifest):
    schema_version: StrictInt = Field(default=1, ge=1, le=1)
    run_id: StrictInt = Field(gt=0)
    simulation: _StrictSimulation | None = None
    live_summary: _StrictSummary | None = None


class _ManifestError(ValueError):
    pass


class _UnsupportedVersion(_ManifestError):
    pass


class _Conflict(ValueError):
    pass


def _load_manifest(artifact_root: Path, manifest_path: Path) -> OutcomeManifest:
    if ".." in artifact_root.parts or ".." in manifest_path.parts:
        raise _ManifestError("manifest path contains traversal")
    root = artifact_root.absolute()
    path = manifest_path.absolute()
    if path.parent.parent != root or path.name != "outcome-v1.json":
        raise _ManifestError("manifest path is outside the owned run directory")
    match = re.fullmatch(r"run-([1-9][0-9]*)", path.parent.name)
    if match is None:
        raise _ManifestError("manifest run directory is invalid")
    expected_run_id = int(match.group(1))
    root_fd = _open_directory_chain(root)
    try:
        directory_fd = os.open(
            path.parent.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd
        )
        try:
            manifest_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
            with os.fdopen(manifest_fd, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise _ManifestError("manifest is not a regular file")
                data = stream.read(MAX_MANIFEST_BYTES + 1)
            if len(data) > MAX_MANIFEST_BYTES:
                raise _ManifestError("manifest exceeds size limit")
            try:
                version = _VersionProbe.model_validate_json(data).schema_version
            except ValidationError:
                raise _ManifestError("manifest is malformed") from None
            if version != 1:
                raise _UnsupportedVersion("unsupported manifest version")
            try:
                manifest = _StrictManifest.model_validate_json(data)
            except ValidationError:
                raise _ManifestError("manifest fails typed validation") from None
            if manifest.run_id != expected_run_id:
                raise _ManifestError("manifest run ID does not match its directory")
            if manifest.intended_status is RunStatus.SUCCEEDED:
                if manifest.partial_artifact_reference is not None:
                    raise _ManifestError("successful manifest contains partial evidence")
            elif (
                manifest.failure_message
                != (
                    manifest.failure_code.value.replace("_", " ")
                    if manifest.failure_code is not None
                    else "live integration failure"
                )
                or manifest.final_artifact_sha256 is not None
            ):
                raise _ManifestError("failed manifest evidence is inconsistent")
            if (
                manifest.partial_artifact_reference is None
                and manifest.partial_artifact_sha256 is not None
            ):
                raise _ManifestError("partial artifact digest has no reference")
            _verify_artifacts(directory_fd, path.parent, manifest)
            return manifest
        finally:
            os.close(directory_fd)
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.ENOTDIR, errno.ENOENT}:
            raise _ManifestError("manifest path is missing or unsafe") from None
        raise
    finally:
        os.close(root_fd)


def _verify_artifacts(directory_fd: int, run_dir: Path, manifest: OutcomeManifest) -> None:
    def verify(reference: str | None, expected: str | None) -> None:
        if reference is None or expected is None:
            raise _ManifestError("manifest artifact evidence is incomplete")
        try:
            name = _validate_reference(reference, run_dir).name
            actual = _sha256(directory_fd, name)
        except OSError, ValueError:
            raise _ManifestError("manifest artifact is missing or unsafe") from None
        if actual != expected:
            raise _ManifestError("manifest artifact hash does not match")

    if manifest.plan_provenance is not None:
        provenance = manifest.plan_provenance

        def load(ref):
            verify(f"run-{manifest.run_id}/{ref.reference}", ref.sha256)
            name = _validate_reference(f"run-{manifest.run_id}/{ref.reference}", run_dir).name
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
            with os.fdopen(descriptor, "rb") as source:
                data = source.read(4 * 1024 * 1024 + 1)
            if len(data) > 4 * 1024 * 1024:
                raise _ManifestError("plan artifact too large")
            return data

        for field in ("receipt", "realized", "comparison", "evaluation", "telemetry", "runtime"):
            ref = getattr(provenance, field)
            if ref is not None:
                if field == "telemetry":
                    verify(f"run-{manifest.run_id}/{ref.reference}", ref.sha256)
                else:
                    load(ref)
        value = PlanEvaluationInput.model_validate_json(load(provenance.input_artifact))
        if (
            plan_hash(value.plan),
            scenario_hash(value.scenario),
            world_manifest_hash(value.scenario.world_manifest),
            value.scenario.world_fingerprint,
        ) != (
            provenance.plan_hash,
            provenance.scenario_hash,
            provenance.manifest_hash,
            provenance.world_fingerprint,
        ):
            raise _ManifestError("plan input identity mismatch")
        if provenance.receipt is not None:
            descriptor = os.open(
                "execution-evidence.log", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd
            )
            with os.fdopen(descriptor, "rb") as source:
                receipt_log = source.read(1024 * 1024 + 1).decode()
            parsed_receipt = parse_execution_evidence(
                receipt_log, value.plan, value.scenario, value.bindings
            )
            if canonical_bytes(parsed_receipt) != load(provenance.receipt):
                raise _ManifestError("receipt identity differs")
        if manifest.intended_status is RunStatus.SUCCEEDED:
            if (
                provenance.receipt is None
                or provenance.realized is None
                or manifest.live_summary is None
            ):
                raise _ManifestError("successful plan lacks evaluation")
            name = "execution-evidence.log"
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
            with os.fdopen(descriptor, "rb") as source:
                log = source.read(1024 * 1024 + 1).decode()
            receipt = accept_execution(value, log)
            if canonical_bytes(receipt) != load(provenance.receipt):
                raise _ManifestError("execution receipt differs")
            realized = RealizedSimulationMetrics.model_validate_json(load(provenance.realized))
            if (
                realized.plan_hash != provenance.plan_hash
                or realized.run_id != manifest.run_id
                or realized.world_fingerprint != provenance.world_fingerprint
                or realized.execution_receipt != provenance.receipt
                or realized.final_save.sha256 != manifest.live_summary.raw_save_sha256
                or realized.final_result.sha256 != manifest.live_summary.parsed_artifact_sha256
            ):
                raise _ManifestError("realized provenance differs")
            for reference in (realized.final_save, realized.final_result):
                verify(f"run-{manifest.run_id}/{reference.reference}", reference.sha256)
            if (
                realized.observations.status,
                realized.observations.received,
                realized.observations.persisted,
                realized.observations.gaps,
                realized.observations.dropped,
            ) != (
                manifest.live_summary.telemetry_status.value,
                manifest.live_summary.received_count,
                manifest.live_summary.persisted_count,
                manifest.live_summary.gap_count,
                manifest.live_summary.dropped_count,
            ):
                raise _ManifestError("realized telemetry coverage differs")
            final_name = _validate_reference(
                f"run-{manifest.run_id}/{realized.final_result.reference}", run_dir
            ).name
            descriptor = os.open(final_name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
            with os.fdopen(descriptor, "rb") as source, gzip.open(source, "rt") as parser:
                parsed = json.load(parser)
            recomputed = realized_metrics(
                value,
                manifest.run_id,
                receipt,
                provenance.receipt,
                start_day=realized.observed_start_day,
                terminal_day=realized.observed_terminal_day,
                coverage=realized.observations,
                final_save=realized.final_save,
                final_result=realized.final_result,
                metrics=final_save_values(parsed, runtime_config(value)),
            )
            if (
                canonical_bytes(recomputed) != canonical_bytes(realized)
                or manifest.live_summary.requested_target_day
                != realized.observed_start_day + value.scenario.horizon_days
                or manifest.live_summary.actual_final_day != realized.observed_terminal_day
            ):
                raise _ManifestError("realized source/horizon differs")
            verify(
                f"run-{manifest.run_id}/{realized.observations.telemetry.reference}",
                realized.observations.telemetry.sha256,
            )
            if value.estimated is not None:
                if provenance.comparison is None or canonical_bytes(
                    compare_metrics(value.estimated, realized)
                ) != load(provenance.comparison):
                    raise _ManifestError("comparison differs")
    if manifest.intended_status is RunStatus.SUCCEEDED:
        if manifest.simulation is None or manifest.live_summary is None:
            raise _ManifestError("successful manifest lacks final evidence")
        verify(manifest.simulation.raw_artifact_reference, manifest.final_artifact_sha256)
        verify(manifest.live_summary.raw_save_reference, manifest.live_summary.raw_save_sha256)
        verify(
            manifest.live_summary.parsed_artifact_reference,
            manifest.live_summary.parsed_artifact_sha256,
        )
    elif manifest.partial_artifact_reference is not None:
        verify(manifest.partial_artifact_reference, manifest.partial_artifact_sha256)
    if manifest.live_summary is not None and manifest.intended_status is RunStatus.FAILED:
        for reference, digest in (
            (manifest.live_summary.raw_save_reference, manifest.live_summary.raw_save_sha256),
            (
                manifest.live_summary.parsed_artifact_reference,
                manifest.live_summary.parsed_artifact_sha256,
            ),
        ):
            if reference is not None:
                verify(reference, digest)


def _stored_config(row: ExperimentRunRecord) -> ExperimentConfig:
    strategy_identifier, strategy_version = row.strategy_identity()
    return ExperimentConfig(
        scenario=ScenarioConfig(
            identifier=row.scenario.identifier,
            version=row.scenario.version,
            openttd_config=row.scenario.openttd_config,
        ),
        planning=PlanningConfiguration(
            strategy_identifier=strategy_identifier,
            strategy_version=strategy_version,
            parameters=row.strategy_configuration,
        ),
        ai=AIConfig.model_validate(row.ai_configuration),
        openttd_version=row.openttd_version,
        opengfx_version=row.opengfx_version,
        seed=row.seed,
        duration_days=row.duration_days,
    )


def _summary_matches(row: LiveTelemetrySessionRecord, summary: LiveExecutionSummary) -> bool:
    return (
        row.received_count == summary.received_count
        and row.persisted_count == summary.persisted_count
        and row.gap_count == summary.gap_count
        and row.dropped_count == summary.dropped_count
        and row.last_observed_sequence == summary.last_sequence
        and row.process_exit_code in {None, summary.process_exit_code}
    )


def _terminal_matches(row: ExperimentRunRecord, manifest: OutcomeManifest) -> bool:
    if (row.input_kind == "execution_plan") != (manifest.plan_provenance is not None):
        return False
    if manifest.plan_provenance is not None and (
        row.plan_evaluation is None
        or row.plan_evaluation.provenance != manifest.plan_provenance.model_dump(mode="json")
    ):
        return False
    live = row.telemetry_session
    summary = manifest.live_summary
    if (
        live is None
        or summary is None
        or not _summary_matches(live, summary)
        or live.telemetry_status != summary.telemetry_status
        or live.process_exit_code != summary.process_exit_code
        or live.terminal_reason
        != (
            manifest.failure_code.value
            if manifest.failure_code is not None
            else "persistence_failure"
            if summary.telemetry_status == "failed"
            else None
        )
    ):
        return False
    metadata = row.execution_metadata or {}
    for name in (
        "raw_save_reference",
        "raw_save_sha256",
        "parsed_artifact_reference",
        "parsed_artifact_sha256",
    ):
        expected_value = getattr(summary, name)
        if expected_value is not None:
            if metadata.get(name) != expected_value:
                return False
    for key, expected_value in (
        ("target_day", summary.requested_target_day),
        ("actual_day", summary.actual_final_day),
    ):
        if expected_value is not None and metadata.get(key) != expected_value:
            return False
    if (
        summary.last_observed_day is not None
        and live.last_observed_day != summary.last_observed_day
    ):
        return False
    if manifest.intended_status is RunStatus.SUCCEEDED:
        expected = manifest.simulation
        stored = row.simulation
        return (
            expected is not None
            and row.status == RunStatus.SUCCEEDED
            and row.failure_code is None
            and stored is not None
            and stored.simulation_date == expected.simulation_date
            and stored.savegame_version == expected.savegame_version
            and row.raw_artifact_reference == expected.raw_artifact_reference
            and sorted((metric.name, metric.value, metric.unit) for metric in stored.metrics)
            == sorted(
                (metric.name, Decimal(str(metric.value)), metric.unit)
                for metric in expected.metrics
            )
        )
    return (
        row.status == RunStatus.FAILED
        and row.simulation is None
        and row.failure_code == manifest.failure_code
        and row.error == manifest.failure_message
        and row.raw_artifact_reference == manifest.partial_artifact_reference
    )


class OutcomeRecoveryService:
    def __init__(
        self,
        session_factory: Callable[[], Session] = create_session,
        repository: ExperimentRepository | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.repository = repository or ExperimentRepository()

    def recover(self, artifact_root: Path, manifest_path: Path) -> RecoveryResult:
        try:
            manifest = _load_manifest(artifact_root, manifest_path)
        except _UnsupportedVersion:
            return RecoveryResult(status=RecoveryStatus.UNSUPPORTED_VERSION)
        except OSError, ValueError:
            return RecoveryResult(status=RecoveryStatus.INVALID_MANIFEST)
        outcome = RecoveryStatus.RECOVERED
        database_error = False
        try:
            with self.session_factory() as session, session.begin():
                row = session.scalar(
                    select(ExperimentRunRecord)
                    .where(ExperimentRunRecord.id == manifest.run_id)
                    .with_for_update()
                )
                if row is None or row.execution_mode != ExecutionMode.LIVE:
                    raise _Conflict("missing or wrong-mode run")
                try:
                    matches_config = config_digest(_stored_config(row)) == manifest.config_sha256
                except ValueError:
                    matches_config = False
                if not matches_config:
                    raise _Conflict("run configuration differs")
                if (row.input_kind == "execution_plan") != (manifest.plan_provenance is not None):
                    raise _Conflict("run input kind differs")
                if manifest.plan_provenance is not None:
                    self.repository.record_plan_provenance(
                        session, manifest.run_id, manifest.plan_provenance
                    )
                live = row.telemetry_session
                summary = manifest.live_summary
                if live is None or summary is None or not _summary_matches(live, summary):
                    raise _Conflict("telemetry evidence differs")
                if row.status != RunStatus.RUNNING:
                    if _terminal_matches(row, manifest):
                        outcome = RecoveryStatus.ALREADY_RECONCILED
                    else:
                        raise _Conflict("terminal outcome differs")
                else:
                    expected_reason = (
                        manifest.failure_code.value
                        if manifest.failure_code is not None
                        else ExecutionFailureCode.PERSISTENCE_FAILURE.value
                        if summary.telemetry_status is TelemetryStatus.FAILED
                        else None
                    )
                    if (
                        live.telemetry_status
                        in {
                            TelemetryStatus.COMPLETE,
                            TelemetryStatus.INCOMPLETE,
                            TelemetryStatus.FAILED,
                        }
                        and live.telemetry_status != summary.telemetry_status
                    ) or live.terminal_reason not in {None, expected_reason}:
                        raise _Conflict("telemetry terminal evidence differs")
                    if any(
                        value is not None
                        for value in (
                            row.completed_at,
                            row.error,
                            row.failure_code,
                            row.raw_artifact_reference,
                            row.simulation,
                        )
                    ):
                        raise _Conflict("running row contains terminal evidence")
                    finished_summary = self.repository.finish_live_session(
                        session,
                        manifest.run_id,
                        manifest.recorded_at,
                        summary=summary,
                        failure_code=manifest.failure_code,
                        error=manifest.failure_message,
                    )
                    if finished_summary.telemetry_status != summary.telemetry_status:
                        raise _Conflict("telemetry terminal status differs")
                    if manifest.intended_status is RunStatus.SUCCEEDED:
                        if manifest.simulation is None:
                            raise _Conflict("successful outcome lacks simulation")
                        self.repository.complete_run(
                            session, manifest.run_id, manifest.simulation, manifest.recorded_at
                        )
                    else:
                        self.repository.fail_run(
                            session,
                            manifest.run_id,
                            manifest.failure_message or "live integration failure",
                            manifest.recorded_at,
                            failure_code=manifest.failure_code,
                            partial_artifact_reference=manifest.partial_artifact_reference,
                        )
        except _Conflict:
            return RecoveryResult(status=RecoveryStatus.CONFLICT, run_id=manifest.run_id)
        except Exception:
            database_error = True
        # A successful commit acknowledgement alone is insufficient to report recovery.
        try:
            with self.session_factory() as verification:
                row = verification.get(ExperimentRunRecord, manifest.run_id)
                if row is None or not _terminal_matches(row, manifest):
                    return RecoveryResult(
                        status=RecoveryStatus.FAILED if database_error else RecoveryStatus.CONFLICT,
                        run_id=manifest.run_id,
                    )
        except Exception:
            return RecoveryResult(status=RecoveryStatus.FAILED, run_id=manifest.run_id)
        try:
            pending = cleanup_abandoned_workspaces(artifact_root, manifest.run_id)
        except OSError, ValueError:
            pending = True
        return RecoveryResult(
            status=outcome, run_id=manifest.run_id, workspace_cleanup_pending=pending
        )
