"""Application-owned experiment contracts, independent of OpenTTDLab records."""

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


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


class ExperimentResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: int
    config: ExperimentConfig
    status: RunStatus
    started_at: datetime
    completed_at: datetime | None = None
    simulation: SimulationResult | None = None
    error: str | None = None
