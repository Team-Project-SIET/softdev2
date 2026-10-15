"""Plan-driven integration with the existing live lifecycle and terminal recovery."""

from __future__ import annotations

import gzip
import json
import math
from datetime import UTC, datetime
from hashlib import md5, sha256
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, model_validator

from app.experiments.domain import (
    AIConfig,
    ExecutionFailure,
    ExecutionFailureCode,
    ExecutionMode,
    ExperimentConfig,
    ExperimentResult,
    LiveExecutionOptions,
    PlanningConfiguration,
    ScenarioConfig,
    SimulationExecutionError,
)
from app.experiments.model import LiveTelemetrySessionRecord
from app.experiments.plan_artifacts import final_save_values, observation_window, telemetry_bytes
from app.experiments.plan_evaluation import (
    PlanEvaluationInput,
    PlanFinalizationFailure,
    PlanProvenance,
    accept_execution,
    realized_metrics,
    retain_bytes,
    retain_inputs,
)
from app.planning.canonical import canonical_bytes, plan_hash, scenario_hash, world_manifest_hash
from app.planning.domain import Digest
from app.planning.execution_evidence import parse_execution_evidence
from app.planning.realized import (
    ArtifactReference,
    ObservationCoverage,
    RealizedSimulationMetrics,
    compare_metrics,
)
from app.planning.transport import transport_bytes, verify_world_source

if TYPE_CHECKING:
    from app.experiments.service import ExperimentService


class PlanEvaluationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    plan_hash: Digest
    outcome: ExperimentResult
    provenance: PlanProvenance
    realized: RealizedSimulationMetrics | None

    @model_validator(mode="after")
    def bound(self):
        if self.plan_hash != self.provenance.plan_hash:
            raise ValueError("evaluation plan identity mismatch")
        if self.realized is not None and (
            self.realized.plan_hash != self.plan_hash
            or self.realized.run_id != self.outcome.run_id
            or self.outcome.simulation is None
        ):
            raise ValueError("realized outcome identity mismatch")
        return self


def runtime_config(value: PlanEvaluationInput) -> ExperimentConfig:
    scenario, plan = value.scenario, value.plan

    def exponent(size):
        if size < 64 or size > 4096 or size & (size - 1):
            raise ValueError("unsupported pinned runtime map dimensions")
        return int(math.log2(size))

    module = transport_bytes(plan, scenario, plan_hash(plan), value.bindings)
    return ExperimentConfig(
        scenario=ScenarioConfig(
            identifier=scenario.scenario_id,
            version=scenario.scenario_version,
            openttd_config=(
                f"[game_creation]\nmap_x = {exponent(scenario.width_tiles)}\n"
                f"map_y = {exponent(scenario.height_tiles)}\n"
                f"starting_year = {scenario.start_date.year}\n"
            ),
        ),
        planning=PlanningConfiguration(
            strategy_identifier=plan.strategy_identifier,
            strategy_version=plan.strategy_version,
            parameters={},
        ),
        ai=AIConfig(
            content_id="50303345",
            name="P03ThinExecutor",
            md5=md5(module, usedforsecurity=False).hexdigest(),
        ),
        openttd_version=scenario.openttd_version,
        opengfx_version=scenario.base_set_version,
        seed=scenario.seed,
        duration_days=scenario.horizon_days,
    )


def default_runner(
    value, world_source, config, options, artifact_root, telemetry_factory, cancellation
):
    from app.simulation.openttd.admin_observer import ExpectedServerIdentity
    from app.simulation.openttd.live_launch import LiveLaunchPreparation
    from app.simulation.openttd.live_runner import LiveSimulationRunner
    from app.simulation.openttd.plan_setup import PlanSetup
    from app.simulation.openttd.runtime_assets import PinnedRuntimePreparer

    return LiveSimulationRunner(
        PinnedRuntimePreparer(artifact_root / ".live-runtime-cache"),
        LiveLaunchPreparation(artifact_root / ".live-workspaces").for_plan(value, world_source),
        expected_identity=ExpectedServerIdentity(
            config.openttd_version,
            config.seed,
            "",
            value.scenario.width_tiles,
            value.scenario.height_tiles,
            0,
        ),
        options=options,
        telemetry_factory=telemetry_factory,
        cancellation=cancellation.event if cancellation else None,
        plan_setup=PlanSetup(value),
    )


def verified_run_artifact(directory, reference, expected):
    path = Path(reference or "")
    if path.is_absolute():
        if path.parent != directory.resolve():
            raise ValueError("artifact outside owned run")
    elif path.parts and path.parts[0] == directory.name:
        path = directory / path.name
    else:
        path = directory / path
    if path.parent != directory or path.is_symlink() or not path.is_file():
        raise ValueError("missing/foreign final artifact")
    digest = sha256(path.read_bytes()).hexdigest()
    if expected is None or digest != expected:
        raise ValueError("final artifact identity mismatch")
    return path, ArtifactReference(reference=path.name, sha256=digest)


def run_plan(
    service: ExperimentService,
    value: PlanEvaluationInput,
    *,
    world_source: Path,
    artifact_dir: Path,
    live_options: LiveExecutionOptions | None = None,
    runner_factory=None,
) -> PlanEvaluationResult:
    # Reparse a canonical snapshot, including nested model_copy changes, before any run exists.
    value = PlanEvaluationInput.model_validate_json(canonical_bytes(value))
    verify_world_source(value.scenario, world_source)
    config = runtime_config(value)
    options = (live_options or LiveExecutionOptions()).resolved_for_duration(config.duration_days)
    from app.simulation.openttd.telemetry_processor import TelemetryProcessor

    if (
        options.persistence_queue_capacity,
        options.persistence_batch_size,
        options.persistence_flush_interval_seconds,
    ) != (
        TelemetryProcessor.CAPACITY,
        TelemetryProcessor.BATCH_SIZE,
        TelemetryProcessor.FLUSH_SECONDS,
    ):
        raise ValueError("unsupported telemetry buffering options")
    provenance = PlanProvenance(
        plan_hash=plan_hash(value.plan),
        world_fingerprint=value.scenario.world_fingerprint,
        scenario_hash=scenario_hash(value.scenario),
        manifest_hash=world_manifest_hash(value.scenario.world_manifest),
        input_artifact=ArtifactReference(
            reference="plan-input.json", sha256=sha256(canonical_bytes(value)).hexdigest()
        ),
    )
    started = datetime.now(UTC)
    with service.session_factory() as session, session.begin():
        run_id = service.repository.create_run(
            session,
            config,
            started,
            execution_mode=ExecutionMode.LIVE,
            execution_metadata={"resolved_options": options.model_dump(mode="json")},
            plan_provenance=provenance,
        )
        service.repository.create_live_session(session, run_id, started)
    directory = artifact_dir.resolve() / f"run-{run_id}"
    realized = None
    runner = None
    simulation = None
    failure = None
    integration_failure = False
    try:
        directory.mkdir(parents=True, exist_ok=False)
        provenance = retain_inputs(value, directory)

        def processor_factory(identifier):
            if identifier != run_id:
                raise ValueError("telemetry run identity mismatch")
            return TelemetryProcessor(
                identifier,
                service.telemetry_store_factory(),
                retry_budget=options.persistence_retry_budget_seconds,
                flush_timeout=options.final_flush_timeout_seconds,
            )

        runner = (runner_factory or default_runner)(
            value,
            world_source,
            config,
            options,
            artifact_dir.resolve(),
            processor_factory,
            service.live_cancellation,
        )
        simulation = runner.run(config, run_id=run_id, artifact_dir=directory)
        # Revalidate the raw evidence independently of any runner-returned object.
        receipt = parse_execution_evidence(
            (directory / "execution-evidence.log").read_text(),
            value.plan,
            value.scenario,
            value.bindings,
        )
        if receipt.code == "PARTIAL_EXECUTION":
            raise SimulationExecutionError(
                ExecutionFailure(
                    code=ExecutionFailureCode.PARTIAL_EXECUTION,
                    message="partial execution",
                    live_summary=simulation.live_summary,
                )
            )
        receipt = accept_execution(value, (directory / "execution-evidence.log").read_text())
        receipt_data = canonical_bytes(receipt)
        if (directory / "execution-receipt.json").read_bytes() != receipt_data:
            raise ValueError("receipt artifact differs from validated evidence")
        provenance = provenance.model_copy(
            update={
                "receipt": ArtifactReference(
                    reference="execution-receipt.json", sha256=sha256(receipt_data).hexdigest()
                )
            }
        )
    except SimulationExecutionError as exc:
        failure = exc.failure
    except Exception:
        failure = ExecutionFailure(
            code=ExecutionFailureCode.PLAN_SETUP_FAILURE,
            message="plan setup evidence rejected",
            live_summary=simulation.live_summary if simulation else None,
        )

    def build_evaluation(session, summary):
        nonlocal provenance, realized
        live = session.get(LiveTelemetrySessionRecord, run_id)
        telemetry_data = telemetry_bytes(session, run_id)
        telemetry = retain_bytes(telemetry_data, directory, "telemetry.json")
        if live is None:
            raise ValueError("missing telemetry session")
        start = runner.plan_setup.observed_start_day if runner is not None else None
        evidence = retain_bytes(
            json.dumps(
                {
                    "schema_version": 1,
                    "plan_hash": provenance.plan_hash,
                    "requested_horizon_days": value.scenario.horizon_days,
                    "observed_start_day": start,
                    "observed_terminal_day": summary.actual_final_day or summary.last_observed_day,
                    "coverage_complete": start is not None
                    and (summary.actual_final_day or summary.last_observed_day or 0)
                    >= start + value.scenario.horizon_days,
                    "telemetry_status": summary.telemetry_status.value,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode(),
            directory,
            "evaluation-evidence.json",
        )
        receipt_path = directory / "execution-receipt.json"
        receipt_ref = (
            ArtifactReference(
                reference=receipt_path.name, sha256=sha256(receipt_path.read_bytes()).hexdigest()
            )
            if receipt_path.is_file()
            else None
        )
        runtime_path = directory / "runtime-provenance.json"
        runtime_ref = (
            ArtifactReference(
                reference=runtime_path.name, sha256=sha256(runtime_path.read_bytes()).hexdigest()
            )
            if runtime_path.is_file()
            else None
        )
        provenance = provenance.model_copy(
            update={
                "evaluation": evidence,
                "telemetry": telemetry,
                "receipt": receipt_ref,
                "runtime": runtime_ref,
            }
        )
        if failure is not None:
            return provenance
        if simulation is None or runner is None or provenance.receipt is None:
            raise ValueError("missing successful plan setup")
        start = runner.plan_setup.observed_start_day
        if (
            start is None
            or summary.requested_target_day != start + value.scenario.horizon_days
            or summary.actual_final_day is None
        ):
            raise ValueError("simulation horizon evidence mismatch")
        receipt = accept_execution(value, (directory / "execution-evidence.log").read_text())
        raw_path, raw_ref = verified_run_artifact(
            directory, summary.raw_save_reference, summary.raw_save_sha256
        )
        parsed_path, parsed_ref = verified_run_artifact(
            directory, summary.parsed_artifact_reference, summary.parsed_artifact_sha256
        )
        with gzip.open(parsed_path, "rt") as source:
            parsed = json.load(source)
        source_metrics = final_save_values(parsed, config)
        window_count, window_complete = observation_window(
            telemetry_data, start, summary.actual_final_day
        )
        coverage = ObservationCoverage(
            status=summary.telemetry_status.value,
            connections=live.connection_count,
            received=summary.received_count,
            persisted=summary.persisted_count,
            gaps=summary.gap_count,
            dropped=summary.dropped_count,
            telemetry=telemetry,
            window_observations=window_count,
            window_complete=window_complete
            and summary.telemetry_status.value == "complete"
            and summary.gap_count == summary.dropped_count == 0,
        )
        realized = realized_metrics(
            value,
            run_id,
            receipt,
            provenance.receipt,
            start_day=start,
            terminal_day=summary.actual_final_day,
            coverage=coverage,
            final_save=raw_ref,
            final_result=parsed_ref,
            metrics=source_metrics,
        )
        ref = retain_bytes(canonical_bytes(realized), directory, "realized.json")
        comparison = (
            retain_bytes(
                canonical_bytes(compare_metrics(value.estimated, realized)),
                directory,
                "comparison.json",
            )
            if value.estimated
            else None
        )
        provenance = provenance.model_copy(update={"realized": ref, "comparison": comparison})
        return provenance

    def finalize(session, summary):
        try:
            return build_evaluation(session, summary)
        except Exception as exc:
            raise PlanFinalizationFailure(provenance) from exc

    outcome = service._record_live_outcome(
        config,
        run_id,
        started,
        directory,
        simulation=simulation if failure is None else None,
        failure=failure,
        integration_failure=integration_failure,
        plan_provenance=provenance,
        plan_finalizer=finalize,
    )
    if outcome.simulation is None:
        realized = None
    return PlanEvaluationResult(
        plan_hash=provenance.plan_hash, outcome=outcome, provenance=provenance, realized=realized
    )
