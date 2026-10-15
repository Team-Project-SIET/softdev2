"""Strict artifact serialization and replay of planning schema v1."""

import json

from pydantic import ValidationError

from app.planning.canonical import (
    _json_value,
    canonical_bytes,
    plan_hash,
    scenario_hash,
    world_manifest_hash,
)
from app.planning.domain import ExecutionPlan, PlanningScenario

__all__ = (
    "canonical_bytes",
    "plan_hash",
    "scenario_hash",
    "world_manifest_hash",
    "verify_plan_hash",
    "plan_artifact_bytes",
    "load_plan_artifact",
)

_MAX_ARTIFACT_BYTES = 4 * 1024 * 1024


def verify_plan_hash(plan: ExecutionPlan, expected: str) -> None:
    from app.planning.validation import PlanningFailureCode, PlanningValidationError

    if len(expected) != 64 or plan_hash(plan) != expected:
        raise PlanningValidationError(PlanningFailureCode.INVALID_PLAN, "plan hash mismatch")


def plan_artifact_bytes(plan: ExecutionPlan) -> bytes:
    payload = {"plan": _json_value(plan), "plan_hash": plan_hash(plan)}
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError(f"nonfinite JSON constant: {value}")


def load_plan_artifact(data: bytes, scenario: PlanningScenario) -> ExecutionPlan:
    """Parse, verify and semantically validate one retained plan before launch."""
    from app.planning.validation import (
        PlanningFailureCode,
        PlanningValidationError,
        validate_execution_plan,
    )

    if len(data) > _MAX_ARTIFACT_BYTES:
        raise PlanningValidationError(PlanningFailureCode.INVALID_PLAN, "artifact too large")
    try:
        document = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PlanningValidationError(
            PlanningFailureCode.INVALID_PLAN, "invalid artifact JSON"
        ) from exc
    if not isinstance(document, dict) or set(document) != {"plan", "plan_hash"}:
        raise PlanningValidationError(PlanningFailureCode.INVALID_PLAN, "invalid artifact envelope")
    payload = document["plan"]
    if not isinstance(payload, dict):
        raise PlanningValidationError(PlanningFailureCode.INVALID_PLAN, "invalid plan object")
    if payload.get("schema_version") != 1:
        raise PlanningValidationError(
            PlanningFailureCode.UNSUPPORTED_PLAN_VERSION, "unsupported planning schema"
        )
    try:
        plan = ExecutionPlan.model_validate_json(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )
    except ValidationError as exc:
        mode_error = any("mode" in str(error["loc"]) for error in exc.errors())
        raise PlanningValidationError(
            PlanningFailureCode.UNSUPPORTED_MODE
            if mode_error
            else PlanningFailureCode.INVALID_PLAN,
            "unsupported mode" if mode_error else "invalid plan fields",
        ) from exc
    expected = document["plan_hash"]
    if not isinstance(expected, str):
        raise PlanningValidationError(PlanningFailureCode.INVALID_PLAN, "invalid plan hash")
    verify_plan_hash(plan, expected)
    validate_execution_plan(plan, scenario)
    return plan
