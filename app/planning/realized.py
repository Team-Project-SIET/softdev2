"""P07 immutable realized values and conservative estimate comparisons.

This boundary contains no runtime, persistence, optimizer, or observation logic.
"""

from decimal import Decimal
from typing import Literal

from pydantic import model_validator

from app.planning.domain import (
    Amount,
    Contract,
    Digest,
    EstimatedPlanMetrics,
    Identifier,
    NonNegativeInt,
    PositiveInt,
)


class ArtifactReference(Contract):
    sha256: Digest
    reference: Identifier


class RealizedValue(Contract):
    name: Identifier
    value: Amount
    unit: Literal["GBP", "cargo_units", "vehicles", "facilities"]
    source: Literal["public_save", "admin"]
    period: Literal["terminal_snapshot", "current_economy_period", "full_horizon"]
    horizon_days: PositiveInt | None

    @model_validator(mode="after")
    def horizon_semantics(self):
        if (self.period == "full_horizon") != (self.horizon_days is not None):
            raise ValueError("full horizon values require an explicit horizon")
        return self


class ObservationCoverage(Contract):
    status: Literal["complete", "incomplete", "failed"]
    connections: NonNegativeInt
    received: NonNegativeInt
    persisted: NonNegativeInt
    gaps: NonNegativeInt
    dropped: NonNegativeInt
    telemetry: ArtifactReference
    window_observations: NonNegativeInt = 0
    window_complete: bool = False


class RealizedSimulationMetrics(Contract):
    schema_version: Literal[1] = 1
    plan_hash: Digest
    run_id: PositiveInt
    world_fingerprint: Digest
    runtime_world_hash: Digest
    manifest_hash: Digest
    scenario_hash: Digest
    scenario_id: Identifier
    scenario_version: Identifier
    planner_name: Identifier
    planner_version: Identifier
    strategy_identifier: Identifier
    strategy_version: Identifier
    executor_version: Identifier
    openttd_version: Identifier
    opengfx_version: Identifier
    execution_receipt: ArtifactReference
    final_save: ArtifactReference
    final_result: ArtifactReference
    requested_horizon_days: PositiveInt
    observed_start_day: NonNegativeInt
    observed_terminal_day: NonNegativeInt
    coverage_complete: bool
    observations: ObservationCoverage
    values: tuple[RealizedValue, ...]

    @model_validator(mode="after")
    def exact_coverage(self):
        if self.observed_terminal_day < self.observed_start_day:
            raise ValueError("terminal date precedes setup")
        if self.coverage_complete != (
            self.observed_terminal_day >= self.observed_start_day + self.requested_horizon_days
        ):
            raise ValueError("coverage disagrees with horizon")
        if len({value.name for value in self.values}) != len(self.values):
            raise ValueError("duplicate realized metric")
        if any(
            value.name in {"net_profit", "infrastructure_spend", "vehicle_purchase_cost"}
            for value in self.values
        ):
            raise ValueError("unsupported authoritative realized metric")
        return self


class MetricComparison(Contract):
    estimated_metric: Identifier
    realized_metric: Identifier | None
    estimated_value: Amount | None
    realized_value: Amount | None
    realized_horizon_days: PositiveInt | None
    units: str
    source: str | None
    estimated_period: Literal["full_horizon"] = "full_horizon"
    realized_period: str | None
    horizon_days: PositiveInt
    compatibility: Literal["compatible", "incompatible", "unavailable"]
    absolute_difference: Amount | None
    relative_difference: Amount | None


def compare_value(
    name: str, estimate: Decimal | None, unit: str, horizon: int, actual: RealizedValue | None
) -> MetricComparison:
    allowed = {
        "predicted_delivered_cargo_units": "cargo_delivered",
        "revenue_gbp": "revenue",
        "estimated_net_profit_gbp": "net_profit",
    }
    compatible = (
        actual is not None
        and allowed.get(name) == actual.name
        and actual.unit == unit
        and actual.period == "full_horizon"
        and actual.horizon_days == horizon
    )
    difference = (
        actual.value - estimate
        if compatible and actual is not None and estimate is not None
        else None
    )
    return MetricComparison(
        estimated_metric=name,
        realized_metric=actual.name if actual else None,
        estimated_value=estimate,
        realized_value=actual.value if actual else None,
        realized_horizon_days=actual.horizon_days if actual else None,
        units=unit,
        source=actual.source if actual else None,
        realized_period=actual.period if actual else None,
        horizon_days=horizon,
        compatibility="unavailable"
        if estimate is None or actual is None
        else "compatible"
        if compatible
        else "incompatible",
        absolute_difference=abs(difference) if difference is not None else None,
        relative_difference=difference / abs(estimate)
        if difference is not None and estimate
        else None,
    )


class EstimateComparison(Contract):
    schema_version: Literal[1] = 1
    plan_hash: Digest
    realized_hash: Digest
    estimated_hash: Digest
    comparisons: tuple[MetricComparison, ...]


def compare_metrics(
    estimated: EstimatedPlanMetrics, realized: RealizedSimulationMetrics
) -> EstimateComparison:
    from hashlib import sha256

    from app.planning.canonical import canonical_bytes

    if estimated.plan_hash != realized.plan_hash:
        raise ValueError("estimate/realized plan identity mismatch")
    actual = {value.name: value for value in realized.values}
    pairs = (
        ("predicted_delivered_cargo_units", "cargo_delivered", "cargo_units"),
        ("revenue_gbp", "current_period_income", "GBP"),
        ("estimated_net_profit_gbp", "current_period_income", "GBP"),
        ("infrastructure_spend_gbp", "infrastructure_spend", "GBP"),
        ("vehicle_purchase_cost_gbp", "vehicle_purchase_cost", "GBP"),
    )
    return EstimateComparison(
        plan_hash=realized.plan_hash,
        realized_hash=sha256(canonical_bytes(realized)).hexdigest(),
        estimated_hash=sha256(canonical_bytes(estimated)).hexdigest(),
        comparisons=tuple(
            compare_value(
                name,
                Decimal(value) if (value := getattr(estimated, name)) is not None else None,
                unit,
                estimated.horizon_days,
                actual.get(metric)
                or (
                    actual.get("current_period_cargo_delivered")
                    if metric == "cargo_delivered"
                    else None
                ),
            )
            for name, metric, unit in pairs
        ),
    )
