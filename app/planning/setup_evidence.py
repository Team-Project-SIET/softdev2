"""Strict terminal setup receipt extracted from the thin AI's bounded log marker."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.planning.domain import Digest, ExecutionPlan, Identifier, PlanningScenario
from app.planning.serialization import plan_hash

MARKER = "P03_EXECUTOR_AI|P03_SETUP_V1|"
STAGE_MARKER = "P03_EXECUTOR_AI|P03_STAGE_V1|"
WORLD_RESOLUTION_MARKER = "P03_EXECUTOR_AI|P03_WORLD_RESOLUTION_V1|"
UNPAUSE_ACK = "__P03_UNPAUSE_ACK__"
_SCRIPT_INFO = re.compile(r"^dbg: \[script\] \[(?P<instance>\d+)\] \[I\] (?P<message>.*)$")
_SCRIPT_ERROR = re.compile(r"^dbg: \[script\] \[\d+\] \[E\] .*$")
_SQUIRREL_TRACE = re.compile(r"^dbg: \[script\] \[(?P<instance>\d+)\] \[S\] (?P<line>.*)$")
_FATAL_PLAN_MISSING = re.compile(
    r"^dbg: \[script\] \[\d+\] \[E\] "
    r"P03_EXECUTOR_AI\|P03_FATAL_V1\|EXECUTOR_SETUP_FAILURE\|PLAN_NOT_FOUND$"
)
_START_AI_LINE = "dbg: [console] Executing cmdline: 'start_ai P03ThinExecutor'"
_STOP_AI_SUCCESS = "AI stopped, company deleted."
_MAX_LOG_BYTES = 1024 * 1024
_WORLD_RESOLUTION_REASONS = {
    "MAP_DIMENSIONS_MISMATCH",
    "SEED_SETTING_UNAVAILABLE",
    "SEED_MISMATCH",
    "TILE_INVALID",
    "INDUSTRY_INVALID",
    "INDUSTRY_NOT_LISTED",
    "INDUSTRY_LOCATION_MISMATCH",
    "INDUSTRY_ID_MISMATCH",
    "STATION_INVALID",
    "STATION_LOCATION_MISMATCH",
    "STATION_ID_MISMATCH",
    "WORLD_KIND_UNSUPPORTED",
}


@dataclass(frozen=True)
class ScriptCrash:
    instance_id: int
    headline: str
    detail: str | None
    last_stage: str
    stack: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorldResolutionFailure:
    instance_id: int
    plan_hash: str
    reason: str
    location_id: str | None
    kind: str | None
    expected_id: int | None
    expected_x: int | None
    expected_y: int | None
    actual: str


@dataclass(frozen=True)
class SetupTrace:
    ai_selected: bool
    old_ai_stopped: bool
    unpause_acknowledged: bool
    api_compatibility_count: int
    script_error_count: int
    start_entered: bool
    plan_found: bool
    world_validation_started: bool
    terminal_count: int
    last_stage: str
    script_crashes: tuple[ScriptCrash, ...] = ()
    world_resolution_failures: tuple[WorldResolutionFailure, ...] = ()


def _script_message(line: str) -> str | None:
    match = _SCRIPT_INFO.fullmatch(line)
    return match.group("message") if match else None


def inspect_setup_log(log: str, expected_plan_hash: str | None = None) -> SetupTrace:
    """Only complete OpenTTD 13.4 script-info lines count as AI evidence."""
    lines = log.splitlines()
    selected = _START_AI_LINE in lines
    stopped = _STOP_AI_SUCCESS in lines
    unpaused = UNPAUSE_ACK in lines
    start = found = world = False
    compatibility_count = 0
    error_count = 0
    terminals = 0
    stages_by_instance: dict[int, str] = {}
    crashes: list[ScriptCrash] = []
    resolution_failures: list[WorldResolutionFailure] = []
    active_crashes: dict[int, int] = {}
    last = "AI_SELECTED" if selected else "PROCESS_STARTED"
    for line in lines:
        squirrel = _SQUIRREL_TRACE.fullmatch(line)
        if squirrel is not None:
            instance = int(squirrel.group("instance"))
            detail = squirrel.group("line")
            if detail.startswith("Your script made an error:"):
                active_crashes[instance] = len(crashes)
                crashes.append(
                    ScriptCrash(instance, detail, None, stages_by_instance.get(instance, last))
                )
                last = "SCRIPT_ERROR"
            elif detail.startswith("[error] "):
                message = detail.removeprefix("[error] ").strip('"')
                index = active_crashes.get(instance)
                if index is None:
                    active_crashes[instance] = len(crashes)
                    crashes.append(
                        ScriptCrash(
                            instance, detail, message, stages_by_instance.get(instance, last)
                        )
                    )
                else:
                    crashes[index] = replace(crashes[index], detail=message)
                last = "SCRIPT_ERROR"
            elif detail.startswith(("*FUNCTION", "*NATIVE")) and instance in active_crashes:
                index = active_crashes[instance]
                current = crashes[index]
                if len(current.stack) < 8:
                    crashes[index] = replace(current, stack=(*current.stack, detail))
            continue
        if _SCRIPT_ERROR.fullmatch(line):
            error_count += 1
            last = "SCRIPT_ERROR"
            continue
        info = _SCRIPT_INFO.fullmatch(line)
        if info is None:
            continue
        instance = int(info.group("instance"))
        message = info.group("message")
        if message == "12 API compatibility in effect.":
            compatibility_count += 1
        if message.startswith(WORLD_RESOLUTION_MARKER):
            parts = message.removeprefix(WORLD_RESOLUTION_MARKER).split("|")
            if (
                len(parts) == 8
                and re.fullmatch(r"[0-9a-f]{64}", parts[0])
                and (expected_plan_hash is None or parts[0] == expected_plan_hash)
                and parts[1] in _WORLD_RESOLUTION_REASONS
                and len(parts[7]) <= 128
            ):
                try:
                    resolution_failures.append(
                        WorldResolutionFailure(
                            instance_id=instance,
                            plan_hash=parts[0],
                            reason=parts[1],
                            location_id=None if parts[2] == "none" else parts[2],
                            kind=None if parts[3] == "none" else parts[3],
                            expected_id=None if parts[4] == "none" else int(parts[4]),
                            expected_x=None if parts[5] == "none" else int(parts[5]),
                            expected_y=None if parts[6] == "none" else int(parts[6]),
                            actual=parts[7],
                        )
                    )
                    last = "WORLD_RESOLUTION_FAILURE"
                    stages_by_instance[instance] = last
                except ValueError:
                    pass
        if message == STAGE_MARKER + "START_ENTERED|none":
            start = True
            last = "START_ENTERED"
            stages_by_instance[instance] = last
        elif message.startswith(STAGE_MARKER + "PLAN_FOUND|"):
            observed = message.removeprefix(STAGE_MARKER + "PLAN_FOUND|")
            if re.fullmatch(r"[0-9a-f]{64}", observed) and (
                expected_plan_hash is None or observed == expected_plan_hash
            ):
                found = True
                last = "PLAN_FOUND"
                stages_by_instance[instance] = last
            else:
                last = "PLAN_HASH_MISMATCH"
        elif message.startswith(STAGE_MARKER + "PLAN_DECODED|"):
            observed = message.removeprefix(STAGE_MARKER + "PLAN_DECODED|")
            if re.fullmatch(r"[0-9a-f]{64}", observed) and (
                expected_plan_hash is None or observed == expected_plan_hash
            ):
                last = "PLAN_DECODED"
                stages_by_instance[instance] = last
            else:
                last = "PLAN_HASH_MISMATCH"
        elif message.startswith(STAGE_MARKER + "WORLD_VALIDATION_STARTED|"):
            observed = message.removeprefix(STAGE_MARKER + "WORLD_VALIDATION_STARTED|")
            if re.fullmatch(r"[0-9a-f]{64}", observed) and (
                expected_plan_hash is None or observed == expected_plan_hash
            ):
                world = True
                last = "WORLD_VALIDATION_STARTED"
                stages_by_instance[instance] = last
            else:
                last = "PLAN_HASH_MISMATCH"
        elif message.startswith(STAGE_MARKER + "WORLD_VALIDATION_SUCCEEDED|"):
            observed = message.removeprefix(STAGE_MARKER + "WORLD_VALIDATION_SUCCEEDED|")
            if re.fullmatch(r"[0-9a-f]{64}", observed) and (
                expected_plan_hash is None or observed == expected_plan_hash
            ):
                last = "WORLD_VALIDATION_SUCCEEDED"
                stages_by_instance[instance] = last
            else:
                last = "PLAN_HASH_MISMATCH"
        elif message.startswith(MARKER):
            terminals += 1
            last = "TERMINAL_EVIDENCE"
    if unpaused and not start and not error_count:
        last = "UNPAUSE_ACKNOWLEDGED"
    if crashes and not terminals:
        last = "SCRIPT_ERROR"
    return SetupTrace(
        selected,
        stopped,
        unpaused,
        compatibility_count,
        error_count + len(crashes),
        start,
        found,
        world,
        terminals,
        last,
        tuple(crashes),
        tuple(resolution_failures),
    )


class SetupLogCapture:
    """Bounded byte-stream assembler; a partial line never counts as evidence."""

    def __init__(self, expected_plan_hash: str | None = None) -> None:
        self._pending = b""
        self._lines: list[str] = []
        self._size = 0
        self._expected_plan_hash = expected_plan_hash

    def feed(self, chunk: bytes) -> None:
        self._size += len(chunk)
        if self._size > _MAX_LOG_BYTES:
            raise SetupEvidenceError("P03 proof log exceeded size limit")
        self._pending += chunk
        while b"\n" in self._pending:
            line, self._pending = self._pending.split(b"\n", 1)
            self._lines.append(line.rstrip(b"\r").decode("utf-8", errors="replace"))

    @property
    def text(self) -> str:
        return "\n".join(self._lines) + ("\n" if self._lines else "")

    @property
    def trace(self) -> SetupTrace:
        return inspect_setup_log(self.text, self._expected_plan_hash)


class SetupFailureCode(StrEnum):
    NONE = "NONE"
    INVALID_FLEET = "INVALID_FLEET"
    UNBUILDABLE_INFRASTRUCTURE = "UNBUILDABLE_INFRASTRUCTURE"
    WORLD_RESOLUTION_FAILURE = "WORLD_RESOLUTION_FAILURE"
    EXECUTOR_SETUP_FAILURE = "EXECUTOR_SETUP_FAILURE"


class SetupEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    transport_version: Literal[1]
    ai_name: Literal["P03ThinExecutor"] = "P03ThinExecutor"
    ai_version: Literal[1]
    status: str = Field(pattern="^(accepted|failed)$")
    code: SetupFailureCode
    plan_hash: Digest
    world_fingerprint: Digest
    world_source_digest: Digest
    scenario_id: Identifier
    scenario_version: Identifier
    route_ids: tuple[Identifier, ...]
    fleet_group_ids: tuple[Identifier, ...]
    infrastructure_action_ids: tuple[Identifier, ...]


class SetupEvidenceError(ValueError):
    def __init__(self, message: str, code: SetupFailureCode | None = None) -> None:
        super().__init__(message)
        self.code = code


def _ids(value: str) -> tuple[str, ...]:
    return tuple(value.split(",")) if value else ()


def parse_setup_evidence(
    log: str, plan: ExecutionPlan, scenario: PlanningScenario
) -> SetupEvidence:
    """Require exactly one terminal marker and bind it to the expected plan/world."""
    records = [
        message
        for line in log.splitlines()
        if (message := _script_message(line)) is not None and message.startswith(MARKER)
    ]
    if len(records) != 1:
        if (
            not records
            and sum(bool(_FATAL_PLAN_MISSING.fullmatch(line)) for line in log.splitlines()) == 1
        ):
            raise SetupEvidenceError(
                "thin AI started but plan transport was absent",
                SetupFailureCode.EXECUTOR_SETUP_FAILURE,
            )
        stage = inspect_setup_log(log, plan_hash(plan)).last_stage
        raise SetupEvidenceError(f"expected exactly one terminal setup marker; last stage: {stage}")
    record = records[0]
    if len(record) > 4096:
        raise SetupEvidenceError("setup marker too large")
    parts = record.split("|")
    if len(parts) != 14 or parts[:2] != ["P03_EXECUTOR_AI", "P03_SETUP_V1"]:
        raise SetupEvidenceError("malformed setup marker")
    if parts[2:4] != ["1", "1"]:
        raise SetupEvidenceError("unsupported evidence or AI version")
    try:
        evidence = SetupEvidence(
            transport_version=1,
            ai_version=1,
            status=parts[4],
            code=SetupFailureCode(parts[5]),
            plan_hash=parts[6],
            world_fingerprint=parts[7],
            world_source_digest=parts[8],
            scenario_id=parts[9],
            scenario_version=parts[10],
            route_ids=_ids(parts[11]),
            fleet_group_ids=_ids(parts[12]),
            infrastructure_action_ids=_ids(parts[13]),
        )
    except (ValueError, ValidationError) as exc:
        raise SetupEvidenceError("invalid setup marker fields") from exc
    if evidence.status == "accepted" and evidence.code is not SetupFailureCode.NONE:
        raise SetupEvidenceError("accepted setup has failure code")
    if evidence.status == "failed" and evidence.code is SetupFailureCode.NONE:
        raise SetupEvidenceError("failed setup lacks failure code")
    if (
        evidence.plan_hash != plan_hash(plan)
        or evidence.world_fingerprint != scenario.world_fingerprint
        or evidence.world_source_digest != scenario.world_manifest.source_digest
        or evidence.scenario_id != scenario.scenario_id
        or evidence.scenario_version != scenario.scenario_version
    ):
        raise SetupEvidenceError("setup evidence identity mismatch")
    if evidence.status == "accepted":
        if (
            evidence.route_ids != tuple(sorted(route.route_id for route in plan.routes))
            or evidence.fleet_group_ids
            != tuple(sorted(group.fleet_group_id for group in plan.fleet.groups))
            or evidence.infrastructure_action_ids
            != tuple(action.construction_id for action in plan.infrastructure.actions)
        ):
            raise SetupEvidenceError("setup evidence plan IDs differ")
    elif evidence.route_ids or evidence.fleet_group_ids or evidence.infrastructure_action_ids:
        raise SetupEvidenceError("failed setup cannot claim accepted IDs")
    return evidence
