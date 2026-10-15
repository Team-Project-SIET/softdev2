"""Explicit P07 inputs, immutable provenance, and independently gated metrics."""

from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import model_validator

from app.planning.canonical import canonical_bytes, plan_hash, scenario_hash, world_manifest_hash
from app.planning.domain import (
    Contract,
    Digest,
    EstimatedPlanMetrics,
    ExecutionPlan,
    PlanningScenario,
)
from app.planning.execution import ExecutionBindings, execution_payload
from app.planning.execution_evidence import (
    ExecutionReceipt,
    ExecutionStage,
    parse_execution_evidence,
)
from app.planning.realized import (
    ArtifactReference,
    ObservationCoverage,
    RealizedSimulationMetrics,
    RealizedValue,
)
from app.planning.validation import validate_execution_plan


class PlanEvaluationInput(Contract):
    scenario: PlanningScenario
    plan: ExecutionPlan
    bindings: ExecutionBindings
    estimated: EstimatedPlanMetrics | None = None

    @model_validator(mode="after")
    def validated(self):
        validate_execution_plan(self.plan, self.scenario)
        execution_payload(self.plan, self.scenario, self.bindings)
        if self.estimated is not None and (
            self.estimated.plan_hash != plan_hash(self.plan)
            or self.estimated.horizon_days != self.scenario.horizon_days
        ):
            raise ValueError("estimate identity/horizon mismatch")
        return self

    @classmethod
    def optimize(cls, scenario: PlanningScenario, bindings: ExecutionBindings):
        from app.planning.optimizer import optimize_candidate_network

        result = optimize_candidate_network(scenario)
        return cls(scenario=scenario, plan=result.plan, bindings=bindings, estimated=result.metrics)


class PlanProvenance(Contract):
    schema_version: Literal[1] = 1
    plan_hash: Digest
    world_fingerprint: Digest
    scenario_hash: Digest
    manifest_hash: Digest
    input_artifact: ArtifactReference
    receipt: ArtifactReference | None = None
    realized: ArtifactReference | None = None
    comparison: ArtifactReference | None = None
    evaluation: ArtifactReference | None = None
    telemetry: ArtifactReference | None = None
    runtime: ArtifactReference | None = None


def retain_bytes(data: bytes, directory: Path, name: str) -> ArtifactReference:
    if Path(name).name != name or name in {".", ".."}:
        raise ValueError("artifact must be run-local")
    path = directory / name
    with path.open("xb") as output:
        output.write(data)
        output.flush()
        import os

        os.fsync(output.fileno())
    path.chmod(0o444)
    return ArtifactReference(sha256=sha256(data).hexdigest(), reference=name)


def retain_inputs(value: PlanEvaluationInput, directory: Path) -> PlanProvenance:
    for name, artifact in (
        ("scenario.json", value.scenario),
        ("manifest.json", value.scenario.world_manifest),
        ("plan.json", value.plan),
        ("bindings.json", value.bindings),
        ("estimated.json", value.estimated),
    ):
        if artifact is not None:
            retain_bytes(canonical_bytes(artifact), directory, name)
    return PlanProvenance(
        plan_hash=plan_hash(value.plan),
        world_fingerprint=value.scenario.world_fingerprint,
        scenario_hash=scenario_hash(value.scenario),
        manifest_hash=world_manifest_hash(value.scenario.world_manifest),
        input_artifact=retain_bytes(canonical_bytes(value), directory, "plan-input.json"),
    )


def accept_execution(value: PlanEvaluationInput, log: str) -> ExecutionReceipt:
    receipt = parse_execution_evidence(log, value.plan, value.scenario, value.bindings)
    if (
        receipt.result != "success"
        or receipt.code != "NONE"
        or receipt.stages != tuple(ExecutionStage)
    ):
        raise ValueError("plan setup did not complete; evaluation invalid")
    return receipt


def realized_metrics(
    value: PlanEvaluationInput,
    run_id: int,
    receipt: ExecutionReceipt,
    receipt_artifact: ArtifactReference,
    *,
    start_day: int,
    terminal_day: int,
    coverage: ObservationCoverage,
    final_save: ArtifactReference,
    final_result: ArtifactReference,
    metrics: tuple[tuple[str, Decimal, str], ...],
) -> RealizedSimulationMetrics:
    if (
        receipt.result != "success"
        or receipt.code != "NONE"
        or receipt.plan_hash != plan_hash(value.plan)
        or receipt.world_fingerprint != value.scenario.world_fingerprint
        or receipt.stages != tuple(ExecutionStage)
    ):
        raise ValueError("invalid execution gate")
    known: dict[str, Literal["terminal_snapshot", "current_economy_period"]] = {
        "company_money": "terminal_snapshot",
        "company_loan": "terminal_snapshot",
        "current_period_income": "current_economy_period",
        "current_period_expenses": "current_economy_period",
        "current_period_cargo_delivered": "current_economy_period",
    }
    units = {"current_period_cargo_delivered": "cargo_units"}
    values = []
    for name, amount, unit in sorted(metrics):
        if name not in known or unit != units.get(name, "GBP"):
            raise ValueError("unsupported final-save metric")
        values.append(
            RealizedValue(
                name=name,
                value=amount,
                unit="cargo_units" if unit == "cargo_units" else "GBP",
                source="public_save",
                period=known[name],
                horizon_days=None,
            )
        )
    plan, scenario = value.plan, value.scenario
    if receipt.runtime_world_hash is None:
        raise ValueError("missing runtime world identity")
    return RealizedSimulationMetrics(
        plan_hash=plan_hash(plan),
        run_id=run_id,
        world_fingerprint=scenario.world_fingerprint,
        runtime_world_hash=receipt.runtime_world_hash,
        manifest_hash=world_manifest_hash(scenario.world_manifest),
        scenario_hash=scenario_hash(scenario),
        scenario_id=scenario.scenario_id,
        scenario_version=scenario.scenario_version,
        planner_name=plan.planner_name,
        planner_version=plan.planner_version,
        strategy_identifier=plan.strategy_identifier,
        strategy_version=plan.strategy_version,
        executor_version=receipt.executor_version,
        openttd_version=scenario.openttd_version,
        opengfx_version=scenario.base_set_version,
        execution_receipt=receipt_artifact,
        final_save=final_save,
        final_result=final_result,
        requested_horizon_days=scenario.horizon_days,
        observed_start_day=start_day,
        observed_terminal_day=terminal_day,
        coverage_complete=terminal_day >= start_day + scenario.horizon_days,
        observations=coverage,
        values=tuple(values),
    )


class PlanFinalizationFailure(ValueError):
    def __init__(self, provenance: PlanProvenance):
        self.provenance = provenance
        super().__init__("plan evaluation finalization failure")
