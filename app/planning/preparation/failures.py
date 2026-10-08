"""Bounded P08 failures; no accepted output accompanies a failure."""

from enum import StrEnum
from typing import Never

from pydantic import Field

from app.planning.domain import Contract, Digest


class PreparationFailureCode(StrEnum):
    UNSUPPORTED_WORLD = "UNSUPPORTED_WORLD"
    EXTRACTION_INCOMPLETE = "EXTRACTION_INCOMPLETE"
    UNKNOWN_CARGO = "UNKNOWN_CARGO"
    NO_COMPATIBLE_DESTINATION = "NO_COMPATIBLE_DESTINATION"
    NO_STATION_CANDIDATE = "NO_STATION_CANDIDATE"
    NO_DEPOT_CANDIDATE = "NO_DEPOT_CANDIDATE"
    NO_FEASIBLE_CORRIDOR = "NO_FEASIBLE_CORRIDOR"
    UNSUPPORTED_TERRAIN = "UNSUPPORTED_TERRAIN"
    FLEET_CATALOG_UNAVAILABLE = "FLEET_CATALOG_UNAVAILABLE"
    CANDIDATE_LIMIT_EXCEEDED = "CANDIDATE_LIMIT_EXCEEDED"
    WORLD_CHANGED_DURING_PREPARATION = "WORLD_CHANGED_DURING_PREPARATION"
    CATALOG_IDENTITY_MISMATCH = "CATALOG_IDENTITY_MISMATCH"
    INVALID_PREPARATION_OUTPUT = "INVALID_PREPARATION_OUTPUT"


class PreparationFailure(Contract):
    code: PreparationFailureCode
    stage: str = Field(min_length=1, max_length=64)
    source_identity: Digest
    affected_object: str | None = Field(default=None, max_length=120)
    message: str = Field(min_length=1, max_length=240)


class PreparationError(ValueError):
    def __init__(self, failure: PreparationFailure):
        self.failure = failure
        self.code = failure.code
        super().__init__(f"{failure.code}: {failure.stage}: {failure.message}")


def fail(
    code: PreparationFailureCode, stage: str, source: str, message: str, affected: str | None = None
) -> Never:
    raise PreparationError(
        PreparationFailure(
            code=code,
            stage=stage,
            source_identity=source,
            affected_object=affected,
            message=message,
        )
    )
