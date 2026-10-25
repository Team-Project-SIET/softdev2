"""Offline run-level analytics over retained native execution attempt records.

This layer answers: what did each retained bounded native attempt (D2 clearing,
D3 clearing/terraforming, D4 road+station corridors) plan and execute at
run level, how do the attempts of one milestone lineage compare, and what do
the retained records say about the effect of plan-schedule revisions between
attempts. It consumes the retained ``PRELAUNCH.json``, ``result.json`` and
``cleanup.json`` records plus consumption markers, never verifies native
evidence again, never launches anything, never connects to AdminPort, never
re-runs a consumed attempt identity and never issues requests.

Discipline inherited from the project's existing analytics modules:

- Every record's own status strings (``PHASE_HALTED_PREFIX_PRESERVED``,
  ``FAILED_CLEANUP``, ``NATIVE_STATE_VERIFIED``, …) and its ``verified`` flag
  are copied verbatim. Nothing is relabeled, and no success metric is computed
  from an unverified or failed attempt: those are reported as failures.
- A field the retained bytes do not state stays UNKNOWN (``None``); no OPEX,
  net profit, ROI, runtime cost or authoritative after-save is invented.
  File presence alone is reported as file presence.
- Budget ceilings and request budgets are retained *plan* values; executed
  counters are retained *result* values; their ratio is DERIVED descriptive
  utilization only, never a performance promise.
- A lineage contrast is descriptive. One or two attempts never claim a trend;
  with three or more attempts a directional sequence may be named, still
  without any causal claim, because the plan revision changed between
  attempts.
"""

from __future__ import annotations

import csv
import hashlib
import json
from html import escape
from pathlib import Path
from statistics import mean
from typing import Any, Literal

from app.experiments.freight_analytics import _bars
from app.planning.domain import Contract

SCHEMA_VERSION = 1

REQUIRED_DOCUMENT = "PRELAUNCH.json"
RESULT_DOCUMENT = "result.json"
CLEANUP_DOCUMENT = "cleanup.json"
CONSUMED_MARKER = "LAUNCH-CONSUMED.json"
CLAIM_FILE = "CLAIM.json"
CLEANUP_FLAG_NAMES = ("reaped", "sockets_closed", "workspace_disposed", "credential_removed")

OUTPUT_NAMES = (
    "execution-metrics.json",
    "attempt-ops.csv",
    "execution-report.md",
    "execution-charts.html",
    "terminal-summary.txt",
)

UNKNOWN = "UNKNOWN"

UNKNOWN_NOTE = "UNKNOWN is not zero; a missing retained field stays UNKNOWN."

STATUS_NOTE = (
    "Native record statuses and verified flags are copied verbatim; nothing is "
    "relabeled and no success is derived from a partial or failed attempt: an "
    "unverified attempt counts as a failure in this document's counts."
)

COMPARISON_POLICY = (
    "Descriptive comparison of retained native execution attempts only; no "
    "causal effectiveness claim, no optimizer or schedule parameter change, no "
    "P05 objective mutation, no candidate staging, no signing and no retry of "
    "any consumed attempt identity. A contrast between one or two attempts "
    "never claims a trend."
)

_FAILURE_NOTE = (
    "Per-op costs come only from retained phase receipts; a dispatched op whose "
    "response evidence is missing keeps cost UNKNOWN (and contributes none), "
    "never an assumed cost."
)

_AFTER_SAVE_NOTE = (
    "File-presence observations never certify an authoritative after-save; "
    "after-save authority is decided by the retained verification records, "
    "not by this analytics layer."
)

_BASE_LIMITATIONS = (
    COMPARISON_POLICY,
    STATUS_NOTE,
    UNKNOWN_NOTE,
    _FAILURE_NOTE,
    _AFTER_SAVE_NOTE,
    "Attempt directories are read-only inputs; this layer writes only its own output directory.",
)


class AttemptPlanned(Contract):
    """Retained plan-side schedule and budgets of one attempt."""

    ops: int | None = None
    by_kind: dict[str, int] | None = None
    run_tiles: int | None = None
    longest_run_tiles: int | None = None
    requests_budget: int | None = None
    road_ops_budget: int | None = None
    launches_budget: int | None = None
    response_bytes_budget: int | None = None
    per_op_max_cost: int | None = None
    schedule_version: int | None = None
    planned_route_pairs: int | None = None


class AttemptExecuted(Contract):
    """Retained result-side observation counters of one attempt."""

    requests: int | None = None
    launches: int | None = None
    connections: int | None = None
    command_accepted: bool | None = None
    dispatch_state: str | None = None
    dispatched_op: str | None = None
    dispatched_request_id: str | None = None
    last_status: str | None = None
    per_record_built_ops: int | None = None
    clearing_command_cost: int | None = None
    funds_at_inspect: int | None = None
    funds_at_exec: int | None = None


class AttemptRecordStatus(Contract):
    """Verbatim outcome fields copied from the retained result record."""

    status: str | None = None
    verification: str | None = None
    verified: bool | None = None
    preflight: str | None = None
    halt_label: str | None = None
    halt_error: str | None = None
    failed_label: str | None = None
    failed_error: str | None = None
    failed_world_state: str | None = None


class CleanupObservation(Contract):
    """Read-only facts from ``cleanup.json`` with fail-closed certification."""

    file_present: bool
    reaped: bool | None = None
    sockets_closed: bool | None = None
    workspace_disposed: bool | None = None
    credential_removed: bool | None = None
    cleanup_errors: tuple[str, ...] = ()
    certification: Literal["PASS", "NOT_PASS", "UNKNOWN"]


class AttemptOp(Contract):
    """One executed-op row copied from the retained phase record."""

    label: str | None = None
    evidence_state: Literal["RECEIPT", "HALT", "PENDING"]
    kind: str | None = None
    operation: str | None = None
    execution_status: str | None = None
    execution_request_id: str | None = None
    cost: int | None = None
    native_quote: int | None = None
    tiles: int | None = None
    verification: str | None = None
    error: str | None = None


class AttemptAnalytics(Contract):
    """Run-level analytics for one retained native attempt directory."""

    name: str
    directory: str
    prelaunch_sha256: str
    result_sha256: str | None = None
    attempt_id: str | None = None
    milestone: str | None = None
    kind: str | None = None
    workspace: str | None = None
    plan_digest: str | None = None
    source_world_sha256: str | None = None
    consumption_marker_present: bool = False
    claim_file_present: bool = False
    planned: AttemptPlanned
    executed: AttemptExecuted
    record_status: AttemptRecordStatus
    cleanup: CleanupObservation
    ops: tuple[AttemptOp, ...] = ()
    derived: dict[str, Any] = {}


class LineageComparison(Contract):
    """Adjacent-attempt deltas inside one milestone lineage."""

    from_attempt: str
    to_attempt: str
    from_schedule_version: int | None = None
    to_schedule_version: int | None = None
    schedule_revised: bool | None = None
    planned_ops_change: int | None = None
    run_tiles_change: int | None = None
    longest_run_change: int | None = None
    requests_budget_change: int | None = None
    receipt_backed_ops_change: int | None = None
    prefix_fraction_change: float | None = None
    from_halt_label: str | None = None
    to_halt_label: str | None = None


class LineageObservation(Contract):
    """One bounded descriptive statement over a lineage."""

    code: str
    statement: str
    attempts: tuple[str, ...]


class MilestoneLineage(Contract):
    """Attempt-group comparison for one milestone (or attempt-name group)."""

    group: str
    attempt_names: tuple[str, ...]
    source_worlds: tuple[str, ...]
    schedule_versions: tuple[int | None, ...]
    comparisons: tuple[LineageComparison, ...] = ()
    observations: tuple[LineageObservation, ...] = ()


class AttemptAnalyticsDocument(Contract):
    """Machine-readable analytics document (schema 1)."""

    schema_version: Literal[1] = 1
    attempts: tuple[AttemptAnalytics, ...]
    lineages: tuple[MilestoneLineage, ...] = ()
    counts: dict[str, int]
    limitations: tuple[str, ...] = ()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_bytes().decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError(f"{path.name}: malformed retained document: {error}") from error


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _bool_or_none(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _str_or_none(value: Any) -> str | None:
    return str(value) if isinstance(value, str) else None


def _ratio(numerator: int | None, denominator: int | float | None) -> float | None:
    if numerator is None or not denominator or denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _fraction(covered: int | None, planned: int | None) -> float | None:
    if covered is None or planned is None or planned <= 0:
        return None
    return round(covered / planned, 4)


def _direction(values: list[float]) -> str:
    if all(later >= earlier for earlier, later in zip(values, values[1:])):
        return "non-decreasing"
    if all(later <= earlier for earlier, later in zip(values, values[1:])):
        return "non-increasing"
    return "mixed"


def _planned_from_plan_policy(prelaunch: dict) -> AttemptPlanned:
    plan_policy = prelaunch.get("plan_policy")
    plan_policy = plan_policy if isinstance(plan_policy, dict) else {}
    budgets = prelaunch.get("budgets")
    budgets = budgets if isinstance(budgets, dict) else {}
    route = plan_policy.get("route")
    route = route if isinstance(route, dict) else {}
    schedule = plan_policy.get("schedule")
    by_kind: dict[str, int] | None = None
    ops: int | None = None
    run_tiles: int | None = None
    longest_run: int | None = None
    road_ops_budget = _int_or_none(budgets.get("road_ops"))
    if isinstance(schedule, list):
        ops = len(schedule)
        kinds = [element.get("kind") for element in schedule if isinstance(element, dict)]
        if all(isinstance(kind, str) for kind in kinds):
            unique_kinds = sorted(dict.fromkeys(kinds))
            by_kind = {kind: kinds.count(kind) for kind in unique_kinds}
            if (
                road_ops_budget is None
                and kinds
                and set(kinds) <= {"full", "road", "station", "depot"}
            ):
                road_ops_budget = sum(kind in ("full", "road") for kind in kinds)
        runs = [
            _int_or_none(element.get("run_len"))
            for element in schedule
            if isinstance(element, dict) and _int_or_none(element.get("run_len")) is not None
        ]
        # The longest retained run is stated from whatever run lengths the
        # schedule declares; the total is stated only when every op declares
        # one, so a partial sum is never presented as the plan total.
        longest_run = max(runs) if runs else None
        if runs and len(runs) == len(schedule):
            run_tiles = sum(runs)
    return AttemptPlanned(
        ops=ops,
        by_kind=by_kind,
        run_tiles=run_tiles,
        longest_run_tiles=longest_run,
        requests_budget=_int_or_none(budgets.get("requests")),
        road_ops_budget=road_ops_budget,
        launches_budget=_int_or_none(budgets.get("launches")),
        response_bytes_budget=_int_or_none(budgets.get("response_bytes")),
        per_op_max_cost=_int_or_none(plan_policy.get("max_cost")),
        schedule_version=_int_or_none(plan_policy.get("schedule_version")),
        planned_route_pairs=_int_or_none(route.get("expected_pairs")),
    )


def _executed_from_result(result: dict) -> AttemptExecuted:
    built = result.get("built_ops")
    raised = result.get("raised_ops")
    per_record = built if isinstance(built, list) else raised if isinstance(raised, list) else None
    attribution = result.get("cost_attribution")
    attribution = attribution if isinstance(attribution, dict) else {}
    return AttemptExecuted(
        requests=_int_or_none(result.get("requests")),
        launches=_int_or_none(result.get("native_launches")),
        connections=_int_or_none(result.get("connections")),
        command_accepted=_bool_or_none(result.get("command_accepted")),
        dispatch_state=_str_or_none(result.get("dispatch_state")),
        dispatched_op=_str_or_none(result.get("dispatched_op")),
        dispatched_request_id=_str_or_none(result.get("dispatched_request_id")),
        last_status=_str_or_none(result.get("last_status")),
        per_record_built_ops=len(per_record) if per_record is not None else None,
        clearing_command_cost=_int_or_none(attribution.get("command_cost")),
        funds_at_inspect=_int_or_none(attribution.get("funds_at_inspect")),
        funds_at_exec=_int_or_none(attribution.get("funds_at_exec")),
    )


def _ops_from_result(result: dict) -> tuple[AttemptOp, ...]:
    phase = result.get("phase")
    phase = phase if isinstance(phase, dict) else {}
    rows: list[AttemptOp] = []
    for receipt in phase.get("completed") or []:
        if not isinstance(receipt, dict):
            continue
        pins = receipt.get("pins")
        pins = pins if isinstance(pins, dict) else {}
        rows.append(
            AttemptOp(
                label=_str_or_none(receipt.get("readback_request_id")),
                evidence_state="RECEIPT",
                kind=_str_or_none(receipt.get("kind")),
                operation=_str_or_none(receipt.get("operation")),
                execution_status=_str_or_none(receipt.get("execution_status")),
                execution_request_id=_str_or_none(receipt.get("execution_request_id")),
                cost=_int_or_none(receipt.get("cost")),
                native_quote=_int_or_none(receipt.get("native_quote")),
                tiles=_int_or_none(pins.get("tiles")),
                verification=_str_or_none(receipt.get("verification")),
            )
        )
    halt = result.get("halt")
    halt = halt if isinstance(halt, dict) else {}
    failed = phase.get("failed")
    failed = failed if isinstance(failed, dict) else {}
    label = failed.get("label") or halt.get("label")
    error = failed.get("error") or halt.get("error")
    if label is not None or error is not None:
        rows.append(
            AttemptOp(
                label=_str_or_none(label),
                evidence_state="HALT",
                error=_str_or_none(error),
            )
        )
    for pending in phase.get("pending") or []:
        rows.append(AttemptOp(label=_str_or_none(pending), evidence_state="PENDING"))
    return tuple(rows)


def _record_status_from_result(result: dict) -> AttemptRecordStatus:
    phase = result.get("phase")
    phase = phase if isinstance(phase, dict) else {}
    halt = result.get("halt")
    halt = halt if isinstance(halt, dict) else {}
    failed = phase.get("failed")
    failed = failed if isinstance(failed, dict) else {}
    verification = _str_or_none(result.get("status"))
    if isinstance(phase.get("verification"), str):
        verification = str(phase["verification"])
    return AttemptRecordStatus(
        status=_str_or_none(result.get("status")),
        verification=verification,
        verified=_bool_or_none(result.get("verified")),
        preflight=_str_or_none(result.get("preflight")),
        halt_label=_str_or_none(halt.get("label")),
        halt_error=_str_or_none(halt.get("error")),
        failed_label=_str_or_none(failed.get("label")),
        failed_error=_str_or_none(failed.get("error")),
        failed_world_state=_str_or_none(failed.get("world_state")),
    )


def halt_label_of(attempt: AttemptAnalytics) -> str | None:
    return (
        attempt.record_status.failed_label
        or attempt.record_status.halt_label
        or next(
            (row.label for row in attempt.ops if row.evidence_state in ("HALT", "PENDING")),
            None,
        )
    )


def _display_name(attempt: AttemptAnalytics) -> str:
    return attempt.attempt_id or attempt.name


def _cleanup_observation(root: Path) -> CleanupObservation:
    path = root / CLEANUP_DOCUMENT
    if not path.is_file():
        return CleanupObservation(file_present=False, cleanup_errors=(), certification="UNKNOWN")
    document = _read_json(path)
    if not isinstance(document, dict):
        raise ValueError(f"{CLEANUP_DOCUMENT}: malformed retained document: object required")
    errors_value = document.get("cleanup_error")
    if isinstance(errors_value, str):
        errors: tuple[str, ...] = (errors_value,)
    elif isinstance(errors_value, list):
        errors = tuple(str(item) for item in errors_value)
    else:
        errors = ()
    flags = {name: _bool_or_none(document.get(name)) for name in CLEANUP_FLAG_NAMES}
    certified = all(value is True for value in flags.values()) and not errors
    return CleanupObservation(
        file_present=True,
        reaped=flags["reaped"],
        sockets_closed=flags["sockets_closed"],
        workspace_disposed=flags["workspace_disposed"],
        credential_removed=flags["credential_removed"],
        cleanup_errors=errors,
        # Fail-closed: a single missing or false condition can never certify
        # PASS. NOT_PASS means the record does not certify every condition;
        # it is not a claim that native cleanup failed.
        certification="PASS" if certified else "NOT_PASS",
    )


def _group_key(attempt: AttemptAnalytics) -> str:
    if attempt.milestone:
        return attempt.milestone
    if attempt.attempt_id:
        return attempt.attempt_id.rsplit("-", 1)[0]
    return attempt.name


def _load_attempt(source: Path) -> AttemptAnalytics:
    root = source.resolve()
    if not root.is_dir():
        raise ValueError(f"not a directory: {source}")
    prelaunch_path = root / REQUIRED_DOCUMENT
    if not prelaunch_path.is_file():
        raise ValueError(f"not a retained native attempt directory: {source}")
    prelaunch = _read_json(prelaunch_path)
    if not isinstance(prelaunch, dict):
        raise ValueError(f"{REQUIRED_DOCUMENT}: malformed retained document: object required")
    result: dict | None = None
    result_sha256: str | None = None
    result_path = root / RESULT_DOCUMENT
    if result_path.is_file():
        loaded = _read_json(result_path)
        if not isinstance(loaded, dict):
            raise ValueError(f"{RESULT_DOCUMENT}: malformed retained document: object required")
        result = loaded
        result_sha256 = _sha256(result_path)
    plan_policy = prelaunch.get("plan_policy")
    plan_policy = plan_policy if isinstance(plan_policy, dict) else {}
    world = prelaunch.get("world")
    world = world if isinstance(world, dict) else {}
    planned = _planned_from_plan_policy(prelaunch)
    executed = _executed_from_result(result) if result is not None else AttemptExecuted()
    record_status = (
        _record_status_from_result(result) if result is not None else AttemptRecordStatus()
    )
    ops = _ops_from_result(result) if result is not None else ()
    receipt_rows = [row for row in ops if row.evidence_state == "RECEIPT"]
    halted = any(row.evidence_state == "HALT" for row in ops)
    costs = [row.cost for row in receipt_rows if row.cost is not None]
    complete_costs = len(costs) == len(receipt_rows) and bool(costs)
    phase_document = (result or {}).get("phase")
    phase_present = isinstance(phase_document, dict)
    # An executed effort with phase receipts counts only receipt-backed rows.
    # Success is measured separately and only when the record itself says
    # verified=true; an unverified attempt's prefix never becomes a success.
    receipt_backed_ops = len(receipt_rows) if phase_present else None
    evidence_prefix = None
    success_ops: int | None = None
    if phase_present and planned.ops is not None:
        evidence_prefix = _fraction(len(receipt_rows), planned.ops)
    if record_status.verified is True:
        success_ops = len(receipt_rows) or executed.per_record_built_ops
    plan_policy_present = bool(plan_policy)
    cleanup = _cleanup_observation(root)
    planned_ops = planned.ops
    totals: dict[str, Any] = {
        "executed_ops_with_receipt": receipt_backed_ops,
        "planned_ops_without_evidence": (
            planned_ops - len(receipt_rows) - (1 if halted else 0)
            if planned_ops is not None and phase_present
            else None
        ),
        "receipt_backed_ops": receipt_backed_ops,
        "success_ops": success_ops,
        "evidence_prefix_fraction": evidence_prefix,
        "op_cost_total": sum(costs) if complete_costs else None,
        "mean_op_cost": (
            round(mean([float(value) for value in costs]), 2) if complete_costs else None
        ),
        "op_cost_max": max(costs) if costs else None,
        "ceiling_utilization_max": (
            _ratio(max(costs), planned.per_op_max_cost)
            if costs and planned.per_op_max_cost is not None
            else None
        ),
        "requests_utilization": _ratio(executed.requests, planned.requests_budget),
        "launches_utilization": _ratio(executed.launches, planned.launches_budget),
        "requests_per_verified_op": _ratio(executed.requests, success_ops),
        "cleanup_certification": cleanup.certification,
    }
    return AttemptAnalytics(
        name=root.name,
        directory=str(root),
        prelaunch_sha256=_sha256(prelaunch_path),
        result_sha256=result_sha256,
        attempt_id=_str_or_none(prelaunch.get("attempt")),
        milestone=_str_or_none(prelaunch.get("milestone")),
        kind=_str_or_none(prelaunch.get("kind")),
        workspace=_str_or_none(prelaunch.get("workspace")),
        plan_digest=_str_or_none(plan_policy.get("plan_digest")) if plan_policy_present else None,
        source_world_sha256=_str_or_none(world.get("save_sha256")),
        consumption_marker_present=(root / CONSUMED_MARKER).is_file(),
        claim_file_present=(root / CLAIM_FILE).is_file(),
        planned=planned,
        executed=executed,
        record_status=record_status,
        cleanup=cleanup,
        ops=ops,
        derived=dict(sorted(totals.items())),
    )


def _comparison(left: AttemptAnalytics, right: AttemptAnalytics) -> LineageComparison:
    def metric_change(getter) -> int | None:
        left_value, right_value = getter(left), getter(right)
        if left_value is None or right_value is None:
            return None
        return right_value - left_value

    receipt_left = _int_or_none(left.derived.get("receipt_backed_ops"))
    receipt_right = _int_or_none(right.derived.get("receipt_backed_ops"))
    fraction_left = left.derived.get("evidence_prefix_fraction")
    fraction_right = right.derived.get("evidence_prefix_fraction")
    versions = (left.planned.schedule_version, right.planned.schedule_version)
    if all(version is not None for version in versions):
        schedule_revised: bool | None = versions[0] != versions[1]
    else:
        planned_change = metric_change(lambda attempt: attempt.planned.ops)
        schedule_revised = (planned_change != 0) if planned_change is not None else None
    return LineageComparison(
        from_attempt=_display_name(left),
        to_attempt=_display_name(right),
        from_schedule_version=versions[0],
        to_schedule_version=versions[1],
        schedule_revised=schedule_revised,
        planned_ops_change=metric_change(lambda attempt: attempt.planned.ops),
        run_tiles_change=metric_change(lambda attempt: attempt.planned.run_tiles),
        longest_run_change=metric_change(lambda attempt: attempt.planned.longest_run_tiles),
        requests_budget_change=metric_change(lambda attempt: attempt.planned.requests_budget),
        receipt_backed_ops_change=(
            receipt_right - receipt_left
            if receipt_left is not None and receipt_right is not None
            else None
        ),
        prefix_fraction_change=(
            round(float(fraction_right) - float(fraction_left), 4)
            if fraction_left is not None and fraction_right is not None
            else None
        ),
        from_halt_label=halt_label_of(left),
        to_halt_label=halt_label_of(right),
    )


def _lineage_observations(
    attempts: tuple[AttemptAnalytics, ...],
    comparisons: tuple[LineageComparison, ...],
) -> tuple[LineageObservation, ...]:
    names = tuple(_display_name(attempt) for attempt in attempts)
    if len(attempts) < 2:
        return (
            LineageObservation(
                code="INSUFFICIENT_ATTEMPTS",
                statement="One retained attempt; no cross-attempt comparison is stated.",
                attempts=names,
            ),
        )
    observations: list[LineageObservation] = []
    revised = [comparison for comparison in comparisons if comparison.schedule_revised is True]
    if revised:
        observations.append(
            LineageObservation(
                code="SCHEDULE_REVISED",
                statement=(
                    "The plan schedule changed between "
                    + " -> ".join(
                        f"{comparison.from_attempt}->{comparison.to_attempt}"
                        for comparison in revised
                    )
                    + "; before-after differences are descriptive contrasts, never "
                    "a causal effect of the revision."
                ),
                attempts=names,
            )
        )
    worlds = {attempt.source_world_sha256 for attempt in attempts if attempt.source_world_sha256}
    if any(attempt.source_world_sha256 is None for attempt in attempts):
        observations.append(
            LineageObservation(
                code="INSUFFICIENT_IDENTITY",
                statement=(
                    "Source-world identity is not retained for every attempt; "
                    "no pooled comparison is stated."
                ),
                attempts=names,
            )
        )
        return tuple(observations)
    if len(worlds) > 1:
        observations.append(
            LineageObservation(
                code="UNRELATED_SOURCE_WORLDS",
                statement=(
                    "Attempts bind different source worlds; they are reported "
                    "side by side and never pooled into one sequence."
                ),
                attempts=names,
            )
        )
        return tuple(observations)
    fractions = [attempt.derived.get("evidence_prefix_fraction") for attempt in attempts]
    if any(fraction is None for fraction in fractions):
        observations.append(
            LineageObservation(
                code="INSUFFICIENT_DATA",
                statement=(
                    "The receipt-backed executed-op fraction is UNKNOWN for at "
                    "least one attempt; no pooled sequence is stated."
                ),
                attempts=names,
            )
        )
        return tuple(observations)
    numeric = [float(fraction) for fraction in fractions]
    halts = " || ".join(
        f"{attempt.name}: "
        + (
            f"halted at {halt_label_of(attempt)} ({_fmt(attempt.record_status.verified)} verified)"
            if halt_label_of(attempt) is not None
            else f"no halt label ({_fmt(attempt.record_status.verified)} verified)"
        )
        for attempt in attempts
    )
    observations.append(
        LineageObservation(
            code="DESCRIPTIVE_EVIDENCE_PREFIX_SEQUENCE",
            statement=(
                "Same source world, "
                f"{_fmt(len(numeric))} retained attempts: receipt-backed "
                "executed-op fractions (each attempt over its own planned ops) "
                "are "
                + " -> ".join(f"{value:g}" for value in numeric)
                + f", a {_direction(numeric)} descriptive contrast. The plan "
                "schedule changed between attempts, so the sequence never "
                "claims a causal effect; records whose verified flag is false "
                "stay outside the verified outcome count."
            ),
            attempts=names,
        )
    )
    observations.append(
        LineageObservation(
            code="HALT_SURFACES",
            statement=f"{halts}. Halt labels are copied verbatim from the retained records.",
            attempts=names,
        )
    )
    return tuple(observations)


def build_lineages(attempts: tuple[AttemptAnalytics, ...]) -> tuple[MilestoneLineage, ...]:
    groups: dict[str, list[AttemptAnalytics]] = {}
    for attempt in attempts:
        groups.setdefault(_group_key(attempt), []).append(attempt)
    lineages: list[MilestoneLineage] = []
    for group, members in sorted(groups.items()):
        members = sorted(members, key=lambda attempt: attempt.name)
        comparisons = tuple(_comparison(left, right) for left, right in zip(members, members[1:]))
        lineages.append(
            MilestoneLineage(
                group=group,
                attempt_names=tuple(_display_name(attempt) for attempt in members),
                source_worlds=tuple(
                    sorted(
                        {
                            attempt.source_world_sha256
                            for attempt in members
                            if attempt.source_world_sha256
                        }
                    )
                ),
                schedule_versions=tuple(attempt.planned.schedule_version for attempt in members),
                comparisons=comparisons,
                observations=_lineage_observations(tuple(members), comparisons),
            )
        )
    return tuple(lineages)


def build_analytics_document(attempts: tuple[AttemptAnalytics, ...]) -> AttemptAnalyticsDocument:
    attempts = tuple(sorted(attempts, key=lambda item: item.name))
    counts = {
        "attempt_total": len(attempts),
        "records_with_result": sum(attempt.result_sha256 is not None for attempt in attempts),
        "verified_outcomes": sum(attempt.record_status.verified is True for attempt in attempts),
        "partial_or_failed_outcomes": sum(
            attempt.record_status.verified is False for attempt in attempts
        ),
        "unknown_outcomes": sum(attempt.record_status.verified is None for attempt in attempts),
        "consumed_attempts": sum(attempt.consumption_marker_present for attempt in attempts),
    }
    return AttemptAnalyticsDocument(
        schema_version=1,
        attempts=attempts,
        lineages=build_lineages(attempts),
        counts=dict(sorted(counts.items())),
        limitations=_BASE_LIMITATIONS,
    )


def analyze_attempts(sources: list[Path], output: Path) -> dict:
    """Analyse retained native attempt directories, writing only ``output``."""
    resolved_sources = [Path(source).resolve() for source in sources]
    if len(set(resolved_sources)) != len(resolved_sources):
        raise ValueError("duplicate attempt directory in sources")
    destinations = [output, *(output / name for name in OUTPUT_NAMES)]
    for root in resolved_sources:
        for target in destinations:
            if target.resolve().is_relative_to(root):
                raise ValueError("analysis output must not modify retained evidence")
    attempts = [_load_attempt(source) for source in resolved_sources]
    identity_dirs: dict[str, str] = {}
    for attempt in attempts:
        if attempt.attempt_id is None:
            continue
        prior = identity_dirs.get(attempt.attempt_id)
        if prior is not None and prior != attempt.name:
            raise ValueError(
                f"attempt identity already analysed from another directory: {attempt.attempt_id}"
            )
        identity_dirs.setdefault(attempt.attempt_id, attempt.name)
    document = build_analytics_document(tuple(attempts))
    output.mkdir(parents=True, exist_ok=True)
    (output / "execution-metrics.json").write_text(document.model_dump_json(indent=2) + "\n")
    with (output / "attempt-ops.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            (
                "attempt",
                "row_kind",
                "label",
                "kind",
                "operation",
                "execution_status",
                "execution_request_id",
                "cost",
                "native_quote",
                "tiles",
                "verification",
                "error",
            )
        )
        for attempt in document.attempts:
            for row in attempt.ops:
                writer.writerow(
                    (
                        attempt.attempt_id or attempt.name,
                        row.evidence_state,
                        row.label,
                        row.kind,
                        row.operation,
                        row.execution_status,
                        row.execution_request_id,
                        row.cost,
                        row.native_quote,
                        row.tiles,
                        row.verification,
                        row.error,
                    )
                )
    (output / "execution-report.md").write_text(render_markdown(document) + "\n")
    (output / "execution-charts.html").write_text(render_charts(document) + "\n")
    (output / "terminal-summary.txt").write_text(render_terminal_summary(document) + "\n")
    counts = document.counts
    return dict(
        attempts=counts["attempt_total"],
        verified_outcomes=counts["verified_outcomes"],
        partial_or_failed_outcomes=counts["partial_or_failed_outcomes"],
        unknown_outcomes=counts["unknown_outcomes"],
        metrics=str(output / "execution-metrics.json"),
        ops_csv=str(output / "attempt-ops.csv"),
        report=str(output / "execution-report.md"),
        charts=str(output / "execution-charts.html"),
        terminal_summary=str(output / "terminal-summary.txt"),
    )


def _fmt(value: Any) -> str:
    if value is None:
        return UNKNOWN
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def render_markdown(document: AttemptAnalyticsDocument) -> str:
    lines = [
        "# Retained native execution attempts — offline analytics",
        "",
        COMPARISON_POLICY,
        "",
        STATUS_NOTE,
        "",
    ]
    counts = document.counts
    lines += [
        f"Attempts: {counts['attempt_total']} · verified outcomes: "
        f"{counts['verified_outcomes']} · partial/failed outcomes: "
        f"{counts['partial_or_failed_outcomes']} · outcome UNKNOWN: "
        f"{counts['unknown_outcomes']} · consumption markers: "
        f"{counts['consumed_attempts']}",
        "",
        _AFTER_SAVE_NOTE,
        "",
    ]
    for attempt in document.attempts:
        planned = attempt.planned
        executed = attempt.executed
        record = attempt.record_status
        lines.append(f"## {attempt.attempt_id or attempt.name} (directory {attempt.name})")
        lines.append("")
        lines.append("| Field | Value |")
        lines.append("|---|---|")
        identity_rows = (
            ("Prelaunch record sha256", "`" + attempt.prelaunch_sha256 + "`"),
            ("Result record sha256", "`" + (attempt.result_sha256 or UNKNOWN) + "`"),
            ("Milestone / kind", f"{attempt.milestone or UNKNOWN} / {attempt.kind or UNKNOWN}"),
            ("Workspace", _fmt(attempt.workspace)),
            ("Plan digest", "`" + (attempt.plan_digest or UNKNOWN) + "`"),
            ("Source world sha256", "`" + (attempt.source_world_sha256 or UNKNOWN) + "`"),
            ("Schedule version", _fmt(planned.schedule_version)),
            ("Planned ops", _fmt(planned.ops)),
            ("Planned ops by kind", json.dumps(planned.by_kind) if planned.by_kind else UNKNOWN),
            ("Planned run tiles", _fmt(planned.run_tiles)),
            ("Longest planned run (tiles)", _fmt(planned.longest_run_tiles)),
            ("Per-op cost ceiling (GBP)", _fmt(planned.per_op_max_cost)),
            ("Request budget", _fmt(planned.requests_budget)),
            ("Road-ops budget", _fmt(planned.road_ops_budget)),
            ("Response-bytes budget", _fmt(planned.response_bytes_budget)),
            ("Planned route pairs", _fmt(planned.planned_route_pairs)),
        )
        executed_rows = (
            ("Requests issued", _fmt(executed.requests)),
            ("Launches", _fmt(executed.launches)),
            ("Connections", _fmt(executed.connections)),
            ("Command accepted (record)", _fmt(executed.command_accepted)),
            ("Dispatch state", _fmt(executed.dispatch_state)),
            ("Dispatched op", _fmt(executed.dispatched_op)),
            ("Dispatched request id", _fmt(executed.dispatched_request_id)),
            ("Last status", _fmt(executed.last_status)),
            ("Per-record built/raised ops", _fmt(executed.per_record_built_ops)),
            ("Clearing command cost (GBP)", _fmt(executed.clearing_command_cost)),
            ("Funds at inspect (GBP)", _fmt(executed.funds_at_inspect)),
            ("Funds at exec (GBP)", _fmt(executed.funds_at_exec)),
        )
        derived_rows = (
            ("Executed ops with receipt", _fmt(attempt.derived.get("executed_ops_with_receipt"))),
            (
                "Planned ops without evidence",
                _fmt(attempt.derived.get("planned_ops_without_evidence")),
            ),
            ("Verified ops (receipt-backed)", _fmt(attempt.derived.get("verified_ops"))),
            (
                "Receipt-backed prefix fraction (own plan)",
                _fmt(attempt.derived.get("evidence_prefix_fraction")),
            ),
            ("Op cost total (GBP)", _fmt(attempt.derived.get("op_cost_total"))),
            ("Mean op cost (GBP)", _fmt(attempt.derived.get("mean_op_cost"))),
            ("Op cost max (GBP)", _fmt(attempt.derived.get("op_cost_max"))),
            ("Ceiling utilization max", _fmt(attempt.derived.get("ceiling_utilization_max"))),
            ("Requests utilization", _fmt(attempt.derived.get("requests_utilization"))),
            ("Launches utilization", _fmt(attempt.derived.get("launches_utilization"))),
            ("Requests per verified op", _fmt(attempt.derived.get("requests_per_verified_op"))),
        )
        outcome_rows = (
            ("Record status", _fmt(record.status)),
            ("Verification state", _fmt(record.verification)),
            ("Verified flag (verbatim)", _fmt(record.verified)),
            ("Preflight (record)", _fmt(record.preflight)),
            ("Halt label", _fmt(record.halt_label or record.failed_label)),
            ("Halt error", _fmt(record.halt_error or record.failed_error)),
            ("Failed world state", _fmt(record.failed_world_state)),
            ("Cleanup file present", _fmt(attempt.cleanup.file_present)),
            ("Cleanup certification", _fmt(attempt.cleanup.certification)),
            ("Cleanup flags", _fmt(_cleanup_flags(attempt))),
            ("Cleanup errors", _fmt(tuple(attempt.cleanup.cleanup_errors) or None)),
            ("Consumption marker (LAUNCH-CONSUMED.json)", _fmt(attempt.consumption_marker_present)),
            ("CLAIM.json present", _fmt(attempt.claim_file_present)),
        )
        unknown_fields = 0
        for field, value in (*identity_rows, *executed_rows, *derived_rows, *outcome_rows):
            if value == UNKNOWN:
                unknown_fields += 1
            lines.append(f"| {field} | {escape(str(value))} |")
        lines.append("")
        if unknown_fields:
            lines.append(
                f"> {unknown_fields} fields UNKNOWN in this attempt; nothing inferred. "
                + UNKNOWN_NOTE
            )
            lines.append("")
        if attempt.ops:
            lines.append("| Op row | State | Op id | Operation | Cost | Quote | Verification |")
            lines.append("|---|---|---|---|---|---|---|")
            for row in attempt.ops:
                lines.append(
                    f"| {escape(_fmt(row.label))} | {row.evidence_state} "
                    f"| {escape(_fmt(row.execution_request_id))} "
                    f"| {escape(_fmt(row.operation))} "
                    f"| {_fmt(row.cost)} | {_fmt(row.native_quote)} "
                    f"| {escape(_fmt(row.verification))} |"
                )
            lines.append("")
    lines.append("## Milestone lineage comparisons")
    lines.append("")
    for lineage in document.lineages:
        lines.append(f"### {lineage.group}")
        lines.append(f"- Attempts: {_fmt(lineage.attempt_names)}")
        lines.append(f"- Source worlds: {len(lineage.source_worlds)} distinct")
        lines.append(f"- Schedule versions: {_fmt(lineage.schedule_versions)}")
        if lineage.comparisons:
            lines.append("")
            lines.append(
                "| From → To | Schedule v | ΔPlanned ops | ΔLongest run "
                "| ΔRequests budget | ΔReceipt-backed ops | ΔPrefix fraction |"
            )
            lines.append("|---|---|---|---|---|---|---|")
            for comparison in lineage.comparisons:
                lines.append(
                    f"| {comparison.from_attempt} → {comparison.to_attempt} "
                    f"| {_fmt(comparison.from_schedule_version)} → "
                    f"{_fmt(comparison.to_schedule_version)} "
                    f"| {_fmt(comparison.planned_ops_change)} "
                    f"| {_fmt(comparison.longest_run_change)} "
                    f"| {_fmt(comparison.requests_budget_change)} "
                    f"| {_fmt(comparison.receipt_backed_ops_change)} "
                    f"| {_fmt(comparison.prefix_fraction_change)} |"
                )
        lines.append("")
        for observation in lineage.observations:
            lines.append(f"- **{observation.code}** — {escape(observation.statement)}")
        lines.append("")
    lines += ["## Limitations", ""]
    lines += [f"- {escape(item)}" for item in document.limitations]
    lines.append("")
    return "\n".join(lines)


def _cleanup_flags(attempt: AttemptAnalytics) -> str:
    cleanup = attempt.cleanup
    if not cleanup.file_present:
        return UNKNOWN
    parts = [f"{name}={_fmt(getattr(cleanup, name))}" for name in CLEANUP_FLAG_NAMES]
    if cleanup.cleanup_errors:
        parts.append(f"errors={_fmt(tuple(cleanup.cleanup_errors))}")
    return "; ".join(parts)


def render_terminal_summary(document: AttemptAnalyticsDocument) -> str:
    counts = document.counts
    lines = [
        "Retained native execution attempts (offline, read-only)",
        f"attempts={counts['attempt_total']} "
        f"verified_outcomes={counts['verified_outcomes']} "
        f"partial_or_failed_outcomes={counts['partial_or_failed_outcomes']} "
        f"outcome_unknown_outcomes={counts['unknown_outcomes']}",
    ]
    for attempt in document.attempts:
        lines.append(
            f"{attempt.attempt_id or attempt.name}: "
            f"status={attempt.record_status.status or UNKNOWN} "
            f"verified={_fmt(attempt.record_status.verified)} "
            f"receipt_ops={_fmt(attempt.derived.get('executed_ops_with_receipt'))} "
            f"planned_ops={_fmt(attempt.planned.ops)} "
            f"prefix={_fmt(attempt.derived.get('evidence_prefix_fraction'))} "
            f"cleanup={attempt.cleanup.certification}"
        )
    for lineage in document.lineages:
        for observation in lineage.observations:
            if observation.code != "INSUFFICIENT_ATTEMPTS":
                lines.append(f"{lineage.group}: {observation.code}")
    return "\n".join(lines)


def render_charts(document: AttemptAnalyticsDocument) -> str:
    sections: list[str] = []
    prefix_rows: list[tuple[str, float | None, str]] = []
    request_rows: list[tuple[str, int | None, str]] = []
    for attempt in document.attempts:
        fraction = attempt.derived.get("evidence_prefix_fraction")
        if fraction is not None:
            prefix_rows.append(
                (
                    attempt.attempt_id or attempt.name,
                    round(float(fraction) * 100, 2),
                    "#176b86",
                )
            )
        if attempt.planned.requests_budget is not None and attempt.executed.requests is not None:
            request_rows.extend(
                (
                    (
                        f"{attempt.attempt_id or attempt.name} issued",
                        attempt.executed.requests,
                        "#176b86",
                    ),
                    (
                        f"{attempt.attempt_id or attempt.name} budget",
                        attempt.planned.requests_budget,
                        "#b66a08",
                    ),
                )
            )
    if prefix_rows:
        sections.append(
            _bars(
                "Receipt-backed executed-op fraction per attempt (percent of its own plan)",
                prefix_rows,
                "percent",
                100,
            )
        )
    if request_rows:
        sections.append(
            _bars("Requests issued vs retained request budget", request_rows, "requests")
        )
    for attempt in document.attempts:
        receipts = [row for row in attempt.ops if row.evidence_state == "RECEIPT"]
        if not receipts or attempt.planned.per_op_max_cost is None:
            continue
        ceiling = attempt.planned.per_op_max_cost
        rows = [
            (row.execution_request_id or row.label or "op", row.native_quote, "#b66a08")
            for row in receipts
        ]
        rows.append((f"per-op ceiling (GBP {ceiling})", ceiling, "#943126"))
        sections.append(
            _bars(
                f"Per-op tested quotes, {attempt.attempt_id or attempt.name} (ceiling £{ceiling})",
                rows,
                "GBP",
                ceiling * 1.3,
            )
        )
    note = (
        "<p>Blue = retained result-side value; orange = retained plan-side value "
        "(a tested quote is result-side but shown against the ceiling). UNKNOWN "
        "stays visible and is never read as zero. Descriptive charts only; no "
        "causal claim.</p>"
    )
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        "<title>Native attempt analytics</title>\n"
        "<style>body{font:16px system-ui;background:#eef2f5;color:#172532;margin:0}\n"
        "main{max-width:1050px;margin:auto;padding:28px}section{background:white;\n"
        "padding:22px;margin:20px 0;border-radius:10px}h1{margin-bottom:8px}\n"
        "svg{width:100%;display:block}svg text{font:14px system-ui;fill:#172532}\n"
        ".axis{fill:#667}.unknown{color:#687580}</style><main>\n"
        "<h1>Retained native execution attempts</h1>\n"
        "<p>Offline analytics over read-only retained records. No launch, "
        "connection, claim, signing or retry.</p>\n"
        + "".join(f"<section>{section}</section>" for section in sections)
        + f"{note}</main></html>"
    )
