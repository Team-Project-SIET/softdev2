"""Application-owned experiment contracts, independent of OpenTTDLab records."""

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StrictBool,
    StrictInt,
    model_serializer,
    model_validator,
)


class ExecutionMode(StrEnum):
    BATCH = "batch"
    LIVE = "live"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


# These constraints describe values only; no options are constructed on the batch path.
PositiveSeconds = Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)]
PositiveCount = Annotated[int, Field(strict=True, gt=0)]


class LiveExecutionOptions(BaseModel):
    """Inert future-runner options, separate from scenario/strategy identity.

    None for running_timeout_seconds means the future runner resolves
    max(300, 5 * duration_days). Constructing these values starts no runtime work.
    Cadences remain daily Date, automatic Info and monthly Economy/Stats as specified;
    port allocation and credentials are not part of this T01 contract.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    startup_timeout_seconds: PositiveSeconds = 120
    handshake_timeout_seconds: PositiveSeconds = 10
    running_timeout_seconds: PositiveSeconds | None = None
    shutdown_timeout_seconds: PositiveSeconds = 15
    terminate_timeout_seconds: PositiveSeconds = 5
    kill_timeout_seconds: PositiveSeconds = 5
    final_parse_timeout_seconds: PositiveSeconds = 30
    final_flush_timeout_seconds: PositiveSeconds = 30
    reconnect_budget_seconds: PositiveSeconds = 15
    heartbeat_interval_seconds: PositiveSeconds = 5
    heartbeat_timeout_seconds: PositiveSeconds = 15
    persistence_retry_budget_seconds: PositiveSeconds = 10
    persistence_flush_interval_seconds: PositiveSeconds = 1
    persistence_batch_size: PositiveCount = 100
    persistence_queue_capacity: PositiveCount = 1024

    @model_validator(mode="after")
    def require_consistent_bounds(self) -> LiveExecutionOptions:
        if self.persistence_batch_size > self.persistence_queue_capacity:
            raise ValueError("persistence batch cannot exceed queue capacity")
        if self.heartbeat_timeout_seconds <= self.heartbeat_interval_seconds:
            raise ValueError("heartbeat timeout must exceed the heartbeat interval")
        return self


class TelemetryStatus(StrEnum):
    PENDING = "pending"
    RECORDING = "recording"
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


class ExecutionFailureCode(StrEnum):
    STARTUP_FAILURE = "startup_failure"
    AUTHENTICATION_FAILURE = "authentication_failure"
    PROTOCOL_FAILURE = "protocol_failure"
    OBSERVER_LOST = "observer_lost"
    PERSISTENCE_FAILURE = "persistence_failure"
    UNEXPECTED_SHUTDOWN = "unexpected_shutdown"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    FINALIZATION_FAILURE = "finalization_failure"
    CLEANUP_FAILURE = "cleanup_failure"


NonNegativeCount = Annotated[int, Field(strict=True, ge=0)]


class LiveExecutionSummary(BaseModel):
    """Execution evidence, never an economic metric or an instruction to run live."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    telemetry_status: TelemetryStatus
    coverage_started_at: AwareDatetime | None = None
    coverage_ended_at: AwareDatetime | None = None
    received_count: NonNegativeCount = 0
    persisted_count: NonNegativeCount = 0
    gap_count: NonNegativeCount = 0
    dropped_count: NonNegativeCount = 0
    last_sequence: PositiveCount | None = None
    last_observed_day: NonNegativeCount | None = None
    process_exit_code: StrictInt | None = None
    requested_target_day: NonNegativeCount | None = None
    actual_final_day: NonNegativeCount | None = None
    raw_save_reference: str | None = None
    raw_save_sha256: str | None = None
    parsed_artifact_reference: str | None = None
    parsed_artifact_sha256: str | None = None
    outcome_manifest_reference: str | None = None
    cleanup_succeeded: StrictBool | None = None
    cleanup_diagnostics: tuple[str, ...] = ()


class ExecutionFailure(BaseModel):
    """Future runner failure context. Producers must supply sanitized diagnostics.

    Carries only already-safe messages/references, never credentials or raw output.
    Merely constructing this metadata does not change the existing service's handling.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: ExecutionFailureCode
    message: str = Field(min_length=1)
    partial_artifact_reference: str | None = None
    last_observed_day: NonNegativeCount | None = None
    process_exit_code: StrictInt | None = None
    cleanup_diagnostics: tuple[str, ...] = ()
    live_summary: LiveExecutionSummary | None = None


class SimulationExecutionError(RuntimeError):
    """Typed failure available to future runners; no new catch/launch behavior."""

    def __init__(self, failure: ExecutionFailure) -> None:
        self.failure = failure
        super().__init__(failure.message)


class ScenarioConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    identifier: str = Field(min_length=1)
    version: str = Field(min_length=1)
    openttd_config: str = ""


class AIConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    content_id: str = Field(pattern=r"^[0-9a-fA-F]{8}$")
    name: str = Field(min_length=1)
    md5: str = Field(pattern=r"^[0-9a-fA-F]{32}$")
    parameters: tuple[tuple[str, str], ...] = ()


class PlanningConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy_identifier: str = Field(min_length=1)
    strategy_version: str = Field(min_length=1)
    parameters: dict[str, str] = Field(default_factory=dict)


class ExperimentConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenario: ScenarioConfig
    planning: PlanningConfiguration
    ai: AIConfig
    openttd_version: str = Field(min_length=1)
    opengfx_version: str = Field(min_length=1)
    seed: int = Field(ge=0, le=2**32 - 1)
    duration_days: int = Field(gt=0)

    @model_validator(mode="after")
    def require_explicit_versions(self) -> ExperimentConfig:
        if self.openttd_version.lower() == "latest" or self.opengfx_version.lower() == "latest":
            raise ValueError("OpenTTD and OpenGFX versions must be pinned")
        return self


class Metric(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    value: float
    unit: str


class SimulationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    simulation_date: date
    savegame_version: int
    metrics: tuple[Metric, ...]
    raw_artifact_reference: str | None = None
    live_summary: LiveExecutionSummary | None = None

    # Let Pydantic retain the model JSON Schema instead of inferring a generic dict.
    @model_serializer(mode="wrap")
    def serialize_result(self, handler: SerializerFunctionWrapHandler):
        result = handler(self)
        if self.live_summary is None:
            result.pop("live_summary", None)
        return result


class ExperimentResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: int
    config: ExperimentConfig
    status: RunStatus
    started_at: datetime
    completed_at: datetime | None = None
    simulation: SimulationResult | None = None
    error: str | None = None
    execution_mode: ExecutionMode = ExecutionMode.BATCH
    failure_code: ExecutionFailureCode | None = None
    live_summary: LiveExecutionSummary | None = None

    # Let Pydantic retain the model JSON Schema instead of inferring a generic dict.
    @model_serializer(mode="wrap")
    def serialize_result(self, handler: SerializerFunctionWrapHandler):
        """Legacy batch exports predate execution metadata; absence means batch."""
        result = handler(self)
        if self.execution_mode is ExecutionMode.BATCH:
            result.pop("execution_mode", None)
        if self.failure_code is None:
            result.pop("failure_code", None)
        if self.live_summary is None:
            result.pop("live_summary", None)
        return result
