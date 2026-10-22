"""Validate the independent random-smoke v1 verdict before authorization consumption."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Check(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    status: Literal["PASS", "FAIL"]
    evidence: str = Field(min_length=1)


class _Verdict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    schema_name: Literal["independent-random-smoke-preflight-v1"] = Field(alias="schema")
    overall: Literal["PASS", "FAIL"]
    classification: Literal["OFFLINE_PREFLIGHT_ONLY"]
    native_launches: int = Field(ge=0, le=0)
    admin_connections: int = Field(ge=0, le=0)
    frozen_inputs_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prelaunch_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checks: dict[str, _Check] = Field(min_length=1)
    runtime_acceptance_pending: list[str]


CHECKS = frozenset(
    (
        "seals_and_source_freeze",
        "runtime_and_assets",
        "effective_generation",
        "resource_and_observation_bounds",
        "one_shot_transport",
        "graphical_spectator",
        "native_package",
        "report_history_paths",
        "cleanup_ownership",
    )
)


def require_independent_preflight(
    value: object, *, frozen_inputs_sha256: str, prelaunch_sha256: str
) -> None:
    """Accept only the retained producer's v1 contract and matching reviewed identities."""
    verdict = _Verdict.model_validate(value)
    if verdict.checks.keys() != CHECKS:
        raise ValueError("Independent preflight check set differs from v1 contract")
    if (
        verdict.frozen_inputs_sha256 != frozen_inputs_sha256
        or verdict.prelaunch_sha256 != prelaunch_sha256
    ):
        raise ValueError("Independent preflight reviewed identity mismatch")
    if verdict.overall == "PASS" and any(c.status != "PASS" for c in verdict.checks.values()):
        raise ValueError("Independent preflight PASS contradicts failed checks")
    if verdict.overall != "PASS":
        raise RuntimeError("Independent preflight did not pass; STOP before launch")
