"""Focused tests for offline native attempt analytics (read-only discipline)."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.experiments.native_attempt_analytics import (
    OUTPUT_NAMES,
    analyze_attempts,
    build_analytics_document,
    build_lineages,
    render_charts,
    render_markdown,
    render_terminal_summary,
)

WORLD = "a" * 64
WORLD_B = "c" * 64
PLAN_DIGEST = "b" * 64

_DEFAULT_SCHEDULE = object()


def _load(root: Path):
    from app.experiments.native_attempt_analytics import _load_attempt

    return _load_attempt(root)


def receipt(index: int, kind: str, cost: int, tiles: int | None = None) -> dict:
    return {
        "execution_request_id": f"{kind}-{index:02d}",
        "execution_status": "BUILT",
        "kind": kind,
        "native_command": "CMD_BUILD_ROAD" if kind != "station" else "CMD_BUILD_ROAD_STATION",
        "native_command_count": 1,
        "native_quote": cost,
        "operation": "ROAD_FULL" if kind == "full" else "ROAD_STATION",
        "pins": {"tiles": tiles},
        "readback_request_id": f"confirm-{index:02d}",
        "schema": "company-corridor-receipt-v1",
        "verification": "NATIVE_STATE_CHANGED",
        "cost": cost,
    }


def receipt_backed_ops(receipts: list[dict]) -> list[str]:
    return [f"op-{index:02d}" for index in range(len(receipts))]


def corridor_result(
    completed: list[dict],
    *,
    halt_label: str | None = None,
    halt_error: str | None = None,
    pending: list[str] | None = None,
    verified: bool = False,
    status: str = "PHASE_HALTED_PREFIX_PRESERVED",
    dispatch_state: str = "CONFIRMED",
    built_ops: list[str] | None = None,
    requests: int = 19,
) -> dict:
    return {
        "command_accepted": True,
        "connections": 1,
        "dispatch_state": dispatch_state,
        "dispatched_op": halt_label,
        "halt": ({"error": halt_error, "label": halt_label} if halt_label or halt_error else None),
        "last_status": "BUILT",
        "native_launches": 1,
        "phase": {
            "completed": completed,
            "failed": (
                {
                    "error": "corridor attempt lacks retained execution evidence",
                    "label": halt_label,
                    "world_state": "UNCERTAIN_AFTER_FAILED_COMMAND",
                }
                if halt_label
                else None
            ),
            "pending": pending or [],
            "schema": "corridor-phase-outcome-v1",
            "verification": "PHASE_COMPLETE" if verified else "PARTIAL_EXECUTION_EVIDENCE",
        },
        "preflight": "PASS",
        "requests": requests,
        "returncode": 0,
        "state_changed": True,
        "status": status,
        "verified": verified,
        "built_ops": receipt_backed_ops(completed) if built_ops is None else built_ops,
    }


def corridor_schedule(version: int, runs: list[int], *, interior_join: bool = False) -> list[dict]:
    schedule: list[dict] = []
    for run_len in runs:
        schedule.append(
            {
                "end": 45999,
                "index": len(schedule),
                "kind": "full",
                "run_len": run_len,
                "start": 48047,
                "tiles": [48047] * run_len,
            }
        )
    schedule.append(
        {
            "end": 45999,
            "index": len(schedule),
            "kind": "road",
            "run_len": 2,
            "start": 45743,
            "tiles": [45743, 45999],
        }
    )
    if interior_join:
        schedule.append(
            {
                "end": 48303,
                "index": len(schedule),
                "kind": "road",
                "run_len": 2,
                "start": 48047,
                "tiles": [48047, 48303],
            }
        )
    schedule.append(
        {
            "front": 45747,
            "index": len(schedule),
            "kind": "station",
            "stop_role": "pickup",
            "tile": 45748,
        }
    )
    schedule.append(
        {
            "front": 50095,
            "index": len(schedule),
            "kind": "station",
            "stop_role": "delivery",
            "tile": 50351,
        }
    )
    schedule.append(
        {
            "front": 45743,
            "index": len(schedule),
            "kind": "depot",
            "orientation": "south",
            "tile": 45487,
        }
    )
    for index, op in enumerate(schedule):
        op["index"] = index
    return schedule


def corridor_prelaunch(
    *,
    attempt_id: str = "D4-CORRIDOR-9",
    version: int | None = 3,
    schedule: list[dict] | None | object = _DEFAULT_SCHEDULE,
    requests_budget: int = 28,
    max_cost: int = 2000,
    world_sha: str = WORLD,
    milestone: str | None = "D4-CONSTRUCTION",
    kind: str | None = "corridor",
    response_bytes: int = 640,
    road_ops: int | None = None,
    with_route: bool = True,
) -> dict:
    if schedule is _DEFAULT_SCHEDULE:
        schedule = corridor_schedule(version or 3, [5, 9, 8])
    budgets: dict = {
        "launches": 1,
        "requests": requests_budget,
        "response_bytes": response_bytes,
    }
    if road_ops is not None:
        budgets["road_ops"] = road_ops
    plan_policy: dict = {
        "max_cost": max_cost,
        "plan_digest": PLAN_DIGEST,
        "schedule_version": version,
    }
    if schedule:
        plan_policy["schedule"] = schedule
    if with_route:
        plan_policy["route"] = {
            "expected_pairs": 23,
            "witness_path": [45748, 45747, 50095, 50351],
        }
    return {
        "attempt": attempt_id,
        "budgets": budgets,
        "kind": kind,
        "milestone": milestone,
        "plan_policy": plan_policy,
        "workspace": "/isolated/ws",
        "world": {
            "mode": "PREREQUISITE_ATTEMPT_SOURCE_SAVE_LOAD",
            "save_sha256": world_sha,
        },
    }


def clean_cleanup() -> dict:
    return {
        "reaped": True,
        "sockets_closed": True,
        "workspace_disposed": True,
        "credential_removed": True,
        "cleanup_error": [],
    }


def write_attempt(
    root: Path,
    prelaunch: dict,
    result: dict | None = None,
    *,
    cleanup: dict | None = None,
    consumed: bool = True,
    claim: bool = True,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "PRELAUNCH.json").write_text(json.dumps(prelaunch))
    if result is not None:
        (root / "result.json").write_text(json.dumps(result))
    if cleanup is not None:
        (root / "cleanup.json").write_text(json.dumps(cleanup))
    if consumed:
        (root / "LAUNCH-CONSUMED.json").write_text("{}")
    if claim:
        (root / "CLAIM.json").write_text("{}")
    return root


def six_receipts() -> list[dict]:
    return [
        receipt(0, "full", 785, 5),
        receipt(1, "full", 1398, 9),
        receipt(2, "full", 1151, 8),
        receipt(3, "road", 71, 2),
        receipt(4, "station", 307),
        receipt(5, "station", 292),
    ]


def test_corridor_run_metrics(tmp_path: Path):
    """Run-level planned/executed arithmetic, prefix fraction and budget uses."""
    result = corridor_result(
        six_receipts(),
        halt_label="op-06",
        halt_error="MalformedMessage: too long",
        requests=19,
    )
    root = write_attempt(
        tmp_path / "attempt-a", corridor_prelaunch(), result, cleanup=clean_cleanup()
    )
    attempt = _load(root)
    assert attempt.planned.ops == 7
    assert attempt.planned.run_tiles is None  # station/depot ops declare no run_len
    assert attempt.planned.longest_run_tiles == 9
    assert attempt.planned.requests_budget == 28
    assert attempt.planned.per_op_max_cost == 2000
    assert attempt.planned.road_ops_budget == 4
    assert attempt.executed.requests == 19
    assert attempt.derived["receipt_backed_ops"] == 6
    assert attempt.derived["evidence_prefix_fraction"] == pytest.approx(0.8571)
    assert attempt.derived["op_cost_total"] == 785 + 1398 + 1151 + 71 + 307 + 292
    assert attempt.derived["op_cost_max"] == 1398
    assert attempt.derived["ceiling_utilization_max"] == pytest.approx(0.699)
    assert attempt.derived["requests_utilization"] == pytest.approx(0.6786)
    assert attempt.derived["planned_ops_without_evidence"] == 0
    assert attempt.derived["success_ops"] is None
    assert attempt.record_status.status == "PHASE_HALTED_PREFIX_PRESERVED"
    assert attempt.record_status.verified is False
    assert attempt.record_status.halt_label == "op-06"
    assert attempt.record_status.halt_error == "MalformedMessage: too long"
    assert attempt.cleanup.certification == "PASS"
    assert attempt.consumption_marker_present is True
    assert attempt.claim_file_present is True
    attempt_opts = [row.evidence_state for row in attempt.ops]
    assert attempt_opts == ["RECEIPT"] * 6 + ["HALT"]
    document = build_analytics_document((attempt,))
    assert document.counts["partial_or_failed_outcomes"] == 1
    assert document.counts["verified_outcomes"] == 0
    assert document.counts["unknown_outcomes"] == 0
    assert document.counts["consumed_attempts"] == 1


def test_unverified_attempt_never_counts_as_success(tmp_path: Path):
    result = corridor_result(six_receipts()[:1], halt_label="op-01", halt_error="admission refused")
    root = write_attempt(tmp_path / "a", corridor_prelaunch(), result)
    document = build_analytics_document((_load(root),))
    assert document.counts["partial_or_failed_outcomes"] == 1
    assert document.counts["verified_outcomes"] == 0


def test_verified_terraform_attempt(tmp_path: Path):
    schedule = [{"index": index, "tile": 1000 + index, "kind": "terraform"} for index in range(16)]
    prelaunch = corridor_prelaunch(
        attempt_id="D3-TERRAFORMING-9",
        milestone="D3-TERRAFORMING",
        kind="terraform",
        version=None,
        schedule=schedule,
        requests_budget=152,
        max_cost=1000,
    )
    completed = [
        dict(receipt(index, "terraform", 200 + index, None), execution_status="RAISED")
        for index in range(16)
    ]
    result = corridor_result(
        completed,
        verified=True,
        status="NATIVE_TERRAFORM_VERIFIED",
        pending=[],
        requests=144,
    )
    result["phase"]["verification"] = "PHASE_COMPLETE"
    result.pop("built_ops")
    result["raised_ops"] = [f"op-{index:02d}" for index in range(2, 18)]
    root = write_attempt(tmp_path / "t", prelaunch, result)
    attempt = _load(root)
    assert attempt.derived["receipt_backed_ops"] == 16
    assert attempt.derived["success_ops"] == 16
    assert attempt.derived["evidence_prefix_fraction"] == pytest.approx(1.0)
    assert attempt.derived["op_cost_total"] == sum(200 + index for index in range(16))
    assert attempt.derived["requests_utilization"] == pytest.approx(0.9474)
    assert attempt.derived["requests_per_verified_op"] == pytest.approx(9.0)
    assert attempt.record_status.status == "NATIVE_TERRAFORM_VERIFIED"
    document = build_analytics_document((attempt,))
    assert document.counts["verified_outcomes"] == 1
    assert document.counts["partial_or_failed_outcomes"] == 0


def test_clearing_attempt_without_schedule(tmp_path: Path):
    prelaunch = corridor_prelaunch(
        attempt_id="D2-CLEARING-9",
        milestone=None,
        kind="clear",
        version=None,
        schedule=None,
        requests_budget=8,
        max_cost=10000,
        with_route=False,
    )
    result = {
        "after_save_sha256": "d" * 64,
        "clearing": "CLEARED",
        "command_accepted": True,
        "connections": 1,
        "cost_attribution": {
            "command_cost": 15,
            "company_cash_delta": 15,
            "funds_at_exec": 499985,
            "funds_at_inspect": 500000,
        },
        "dispatch_state": "CONFIRMED",
        "dispatched_request_id": "clear-1",
        "native_launches": 1,
        "preflight": "PASS",
        "requests": 4,
        "status": "NATIVE_STATE_VERIFIED",
        "verified": True,
    }
    root = write_attempt(tmp_path / "c", prelaunch, result)
    attempt = _load(root)
    assert attempt.planned.ops is None
    assert attempt.planned.requests_budget == 8
    assert attempt.executed.clearing_command_cost == 15
    assert attempt.executed.funds_at_inspect == 500000
    assert attempt.executed.funds_at_exec == 499985
    assert attempt.derived["executed_ops_with_receipt"] is None
    assert attempt.derived["evidence_prefix_fraction"] is None
    assert attempt.derived["success_ops"] is None
    assert attempt.derived["requests_utilization"] == pytest.approx(0.5)
    document = build_analytics_document((attempt,))
    assert document.counts["unknown_outcomes"] == 0
    lineage = build_lineages((attempt,))[0]
    assert lineage.observations[0].code == "INSUFFICIENT_ATTEMPTS"


def test_cleanup_certifications_fail_closed(tmp_path: Path):
    result = corridor_result(six_receipts()[:1], halt_label="op-01", halt_error="x")
    cases = (
        (
            "missing-socket",
            {
                "reaped": True,
                "workspace_disposed": True,
                "credential_removed": True,
                "cleanup_error": [],
            },
            "NOT_PASS",
        ),
        ("false-flag", {**clean_cleanup(), "credential_removed": False}, "NOT_PASS"),
        ("with-error", {**clean_cleanup(), "cleanup_error": ["boom"]}, "NOT_PASS"),
        ("clean", clean_cleanup(), "PASS"),
    )
    for name, cleanup, expected in cases:
        root = write_attempt(
            tmp_path / name,
            corridor_prelaunch(attempt_id=f"D4-X-{name}"),
            result,
            cleanup=cleanup,
        )
        attempt = _load(root)
        assert attempt.cleanup.certification == expected
    root = write_attempt(
        tmp_path / "no-cleanup",
        corridor_prelaunch(attempt_id="D4-X-NC"),
        result,
        cleanup=None,
        consumed=False,
        claim=False,
    )
    attempt = _load(root)
    assert attempt.cleanup.certification == "UNKNOWN"
    assert attempt.consumption_marker_present is False
    assert attempt.claim_file_present is False


def test_missing_result_stays_unknown(tmp_path: Path):
    root = write_attempt(tmp_path / "staged", corridor_prelaunch(), None, cleanup=clean_cleanup())
    attempt = _load(root)
    assert attempt.record_status.status is None
    assert attempt.record_status.verified is None
    assert attempt.derived["executed_ops_with_receipt"] is None
    assert attempt.derived["evidence_prefix_fraction"] is None
    assert attempt.result_sha256 is None
    document = build_analytics_document((attempt,))
    assert document.counts["unknown_outcomes"] == 1
    assert document.counts["records_with_result"] == 0


@pytest.mark.parametrize("target", ["PRELAUNCH.json", "result.json"])
@pytest.mark.parametrize("payload", [b"{not json", b"[1, 2, 3]", b"true"])
def test_malformed_documents_reject_cleanly(tmp_path: Path, target: str, payload: bytes):
    root = write_attempt(tmp_path / "a", corridor_prelaunch(attempt_id="D4-Q-1"), None)
    if target == "result.json":
        (root / "result.json").write_bytes(payload)
    else:
        (root / "PRELAUNCH.json").write_bytes(payload)
    with pytest.raises(ValueError, match="malformed retained document"):
        analyze_attempts([root], tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_non_attempt_directory_rejected(tmp_path: Path):
    root = tmp_path / "empty"
    root.mkdir()
    (root / "readme.txt").write_text("not an attempt")
    with pytest.raises(ValueError, match="not a retained native attempt directory"):
        analyze_attempts([root], tmp_path / "out")
    with pytest.raises(ValueError, match="not a directory"):
        analyze_attempts([tmp_path / "absent"], tmp_path / "out")


def test_conflicting_attempt_identity_rejected(tmp_path: Path):
    write_attempt(
        tmp_path / "one",
        corridor_prelaunch(attempt_id="D4-K-1"),
        corridor_result(six_receipts()[:1]),
    )
    write_attempt(
        tmp_path / "two",
        corridor_prelaunch(attempt_id="D4-K-1"),
        corridor_result(six_receipts()[:2]),
    )
    with pytest.raises(ValueError, match="attempt identity already analysed"):
        analyze_attempts([tmp_path / "one", tmp_path / "two"], tmp_path / "out")
        analyze_attempts([tmp_path / "one", tmp_path / "two"], tmp_path / "out")


def test_duplicate_source_rejected(tmp_path: Path):
    root = write_attempt(
        tmp_path / "one", corridor_prelaunch(), corridor_result(six_receipts()[:1])
    )
    with pytest.raises(ValueError, match="duplicate attempt directory"):
        analyze_attempts([root, root], tmp_path / "out")


def test_unrelated_source_worlds_not_pooled(tmp_path: Path):
    first = write_attempt(
        tmp_path / "world-a",
        corridor_prelaunch(attempt_id="D4-L-1"),
        corridor_result(six_receipts()[:1], halt_label="op-01", halt_error="x"),
    )
    second = write_attempt(
        tmp_path / "world-b",
        corridor_prelaunch(attempt_id="D4-L-2", world_sha=WORLD_B),
        corridor_result(six_receipts()[:2], halt_label="op-02", halt_error="y"),
    )
    document = build_analytics_document((_load(first), _load(second)))
    codes = [observation.code for observation in document.lineages[0].observations]
    assert "UNRELATED_SOURCE_WORLDS" in codes
    assert "DESCRIPTIVE_EVIDENCE_PREFIX_SEQUENCE" not in codes


def test_failed_outcomes_never_hide_the_failure(tmp_path: Path):
    first = write_attempt(
        tmp_path / "a",
        corridor_prelaunch(attempt_id="D4-M-1", version=1, schedule=corridor_schedule(1, [5, 17])),
        corridor_result(six_receipts()[:1], halt_label="op-01", halt_error="x"),
    )
    second = write_attempt(
        tmp_path / "b",
        corridor_prelaunch(
            attempt_id="D4-M-2",
            version=2,
            schedule=corridor_schedule(2, [5, 9, 8], interior_join=True),
            requests_budget=31,
        ),
        corridor_result(six_receipts()[:3], halt_label="op-03", halt_error="y"),
    )
    document = build_analytics_document((_load(first), _load(second)))
    lineage = document.lineages[0]
    codes = [observation.code for observation in lineage.observations]
    assert "DESCRIPTIVE_EVIDENCE_PREFIX_SEQUENCE" in codes
    assert "SCHEDULE_REVISED" in codes
    sequence = next(
        observation
        for observation in lineage.observations
        if observation.code == "DESCRIPTIVE_EVIDENCE_PREFIX_SEQUENCE"
    )
    assert "never claims a causal effect" in sequence.statement
    assert "stay outside the verified outcome count" in sequence.statement
    assert document.counts["partial_or_failed_outcomes"] == 2
    comparison = lineage.comparisons[0]
    assert comparison.planned_ops_change == 2
    assert comparison.longest_run_change == -8
    assert comparison.requests_budget_change == 3
    assert comparison.receipt_backed_ops_change == 2
    assert comparison.prefix_fraction_change == pytest.approx(0.2083)
    assert comparison.from_halt_label == "op-01"
    assert comparison.to_halt_label == "op-03"


def test_three_attempt_sequence_and_deltas(tmp_path: Path):
    first = write_attempt(
        tmp_path / "a",
        corridor_prelaunch(
            attempt_id="D4-N-1",
            version=1,
            schedule=corridor_schedule(1, [5, 17]),
            requests_budget=25,
        ),
        corridor_result(six_receipts()[:1], halt_label="op-01", halt_error="x", requests=4),
    )
    second = write_attempt(
        tmp_path / "b",
        corridor_prelaunch(
            attempt_id="D4-N-2",
            version=2,
            schedule=corridor_schedule(2, [5, 9, 8], interior_join=True),
            requests_budget=31,
        ),
        corridor_result(six_receipts()[:3], halt_label="op-03", halt_error="y", requests=10),
    )
    third = write_attempt(
        tmp_path / "c",
        corridor_prelaunch(
            attempt_id="D4-N-3",
            version=3,
            schedule=corridor_schedule(3, [5, 9, 8]),
            requests_budget=28,
        ),
        corridor_result(six_receipts(), halt_label="op-06", halt_error="z", requests=19),
    )
    document = build_analytics_document((_load(first), _load(second), _load(third)))
    lineage = document.lineages[0]
    codes = [observation.code for observation in lineage.observations]
    assert "DESCRIPTIVE_EVIDENCE_PREFIX_SEQUENCE" in codes
    assert "SCHEDULE_REVISED" in codes
    assert "HALT_SURFACES" in codes
    sequence = next(
        observation
        for observation in lineage.observations
        if observation.code == "DESCRIPTIVE_EVIDENCE_PREFIX_SEQUENCE"
    )
    assert "0.1667 -> 0.375 -> 0.8571" in sequence.statement
    comparisons = lineage.comparisons
    assert [comparison.planned_ops_change for comparison in comparisons] == [2, -1]
    assert [comparison.longest_run_change for comparison in comparisons] == [-8, 0]
    assert [comparison.requests_budget_change for comparison in comparisons] == [6, -3]
    assert [comparison.receipt_backed_ops_change for comparison in comparisons] == [2, 3]
    assert [comparison.from_halt_label for comparison in comparisons] == ["op-01", "op-03"]
    assert [comparison.to_halt_label for comparison in comparisons] == ["op-03", "op-06"]
    assert comparisons[1].schedule_revised is True
    assert comparisons[0].schedule_revised is True


def test_mixed_sequences_do_not_claim_a_direction(tmp_path: Path):
    plans = (
        ("D4-Z-1", [5, 17], six_receipts()[:3], "op-03"),  # fraction 3/8
        ("D4-Z-2", [5, 9, 8], six_receipts()[:1], "op-01"),  # fraction 1/7
        ("D4-Z-3", [5, 9, 8], six_receipts(), "op-06"),  # fraction 6/7
    )
    attempts = []
    for attempt_id, runs, receipts, halt in plans:
        version = int(attempt_id[-1]) + 1
        root = write_attempt(
            tmp_path / attempt_id,
            corridor_prelaunch(
                attempt_id=attempt_id,
                version=version,
                schedule=corridor_schedule(
                    version,
                    [17 if runs == [5, 17] else 9, *runs[1:]],
                ),
            ),
            corridor_result(receipts, halt_label=halt, halt_error="x"),
        )
        attempts.append(_load(root))
    document = build_analytics_document(tuple(attempts))
    sequence = next(
        observation
        for observation in document.lineages[0].observations
        if observation.code == "DESCRIPTIVE_EVIDENCE_PREFIX_SEQUENCE"
    )
    assert "mixed descriptive contrast" in sequence.statement


def test_schedule_revised_fallback_without_versions(tmp_path: Path):
    first = write_attempt(
        tmp_path / "a",
        corridor_prelaunch(attempt_id="D4-P-1", version=None, requests_budget=27),
        corridor_result(six_receipts()[:1]),
    )
    second = write_attempt(
        tmp_path / "b",
        corridor_prelaunch(attempt_id="D4-P-2", version=None),
        corridor_result(six_receipts()[:1]),
    )
    document = build_analytics_document((_load(first), _load(second)))
    comparison = document.lineages[0].comparisons[0]
    assert comparison.schedule_revised is False
    assert comparison.from_schedule_version is None
    assert comparison.to_schedule_version is None
    assert comparison.requests_budget_change == 1


def test_missing_world_identity_not_pooled(tmp_path: Path):
    first = write_attempt(
        tmp_path / "a",
        corridor_prelaunch(attempt_id="D4-R-1"),
        corridor_result(six_receipts()[:1]),
    )
    prelaunch = corridor_prelaunch(attempt_id="D4-R-2")
    prelaunch["world"] = {"mode": "SOMETHING_ELSE"}
    second = write_attempt(tmp_path / "b", prelaunch, corridor_result(six_receipts()[:2]))
    document = build_analytics_document((_load(first), _load(second)))
    codes = [observation.code for observation in document.lineages[0].observations]
    assert "INSUFFICIENT_IDENTITY" in codes
    assert "DESCRIPTIVE_EVIDENCE_PREFIX_SEQUENCE" not in codes


def test_run_tiles_require_complete_run_lengths(tmp_path: Path):
    prelaunch = corridor_prelaunch()
    schedule = prelaunch["plan_policy"]["schedule"]
    assert {op["kind"] for op in schedule} == {"full", "road", "station", "depot"}
    prelaunch["plan_policy"]["schedule"] = schedule
    root = write_attempt(tmp_path / "a", prelaunch, corridor_result(six_receipts()[:1]))
    attempt = _load(root)
    assert attempt.planned.longest_run_tiles == 9
    assert attempt.planned.run_tiles is None


def test_run_tiles_sum_when_every_op_declares_run_len(tmp_path: Path):
    prelaunch = corridor_prelaunch()
    schedule = prelaunch["plan_policy"]["schedule"]
    for op in schedule:
        op.setdefault("run_len", 1)
    root = write_attempt(tmp_path / "a", prelaunch, corridor_result(six_receipts()))
    attempt = _load(root)
    assert attempt.planned.run_tiles == sum(op["run_len"] for op in schedule)
    assert attempt.planned.longest_run_tiles == 9


def test_output_refused_inside_source(tmp_path: Path):
    root = write_attempt(tmp_path / "a", corridor_prelaunch(), corridor_result(six_receipts()[:1]))
    with pytest.raises(ValueError, match="must not modify retained evidence"):
        analyze_attempts([root], root / "insights")
    with pytest.raises(ValueError, match="must not modify retained evidence"):
        analyze_attempts([root], root / "execution-metrics.json")
    assert not (root / "insights").exists()


def test_inputs_unchanged_after_analysis(tmp_path: Path):
    result = corridor_result(six_receipts(), halt_label="op-06", halt_error="x")
    root = write_attempt(tmp_path / "a", corridor_prelaunch(), result, cleanup=clean_cleanup())
    before = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.iterdir())
        if path.is_file()
    }
    analyze_attempts([root], tmp_path / "out")
    after = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.iterdir())
        if path.is_file()
    }
    assert before == after
    assert set(before) >= {"PRELAUNCH.json", "result.json", "cleanup.json"}


def test_outputs_are_deterministic(tmp_path: Path):
    result = corridor_result(six_receipts(), halt_label="op-06", halt_error="x")
    root = write_attempt(tmp_path / "a", corridor_prelaunch(), result, cleanup=clean_cleanup())
    analyze_attempts([root], tmp_path / "one")
    analyze_attempts([root], tmp_path / "two")
    for name in OUTPUT_NAMES:
        assert (tmp_path / "one" / name).read_bytes() == (tmp_path / "two" / name).read_bytes()


def test_csv_rows_cover_receipts_halts_and_pending(tmp_path: Path):
    result = corridor_result(
        six_receipts()[:2],
        halt_label="op-02",
        halt_error="not buildable",
        pending=["op-03", "op-04", "op-05", "op-06"],
    )
    root = write_attempt(tmp_path / "a", corridor_prelaunch(), result)
    result_map = analyze_attempts([root], tmp_path / "out")
    rows = Path(result_map["ops_csv"]).read_text().splitlines()
    assert rows[0].startswith("attempt,row_kind,label")
    kinds = [row.split(",")[1] for row in rows[1:]]
    assert kinds.count("RECEIPT") == 2
    assert kinds.count("HALT") == 1
    assert kinds.count("PENDING") == 4
    assert rows[1].startswith("D4-CORRIDOR-9,RECEIPT,confirm-00")
    halt_row = next(row for row in rows[1:] if ",HALT," in row)
    assert "corridor attempt lacks retained execution evidence" in halt_row


def test_report_and_charts_render_unknown_visibly(tmp_path: Path):
    result = corridor_result(six_receipts()[:1], halt_label="op-01", halt_error="admission refused")
    root = write_attempt(tmp_path / "a", corridor_prelaunch(), result)
    document = build_analytics_document((_load(root),))
    markdown = render_markdown(document)
    assert "| Record status | PHASE_HALTED_PREFIX_PRESERVED |" in markdown
    assert "| Verified flag (verbatim) | False |" in markdown
    assert "UNKNOWN" in markdown
    assert "nothing inferred" in markdown
    assert "COMPARISON_POLICY"[:4] not in markdown  # constants are text, not names
    charts = render_charts(document)
    assert "unknown" in charts
    summary = render_terminal_summary(document)
    assert "attempts=1" in summary
    assert "prefix=0.1429" in summary


def test_requests_per_verified_op_guard(tmp_path: Path):
    # A verified attempt with phase receipts of zero cannot divide by zero.
    prelaunch = corridor_prelaunch(attempt_id="D5-CLEAR-1", version=None, schedule=[], kind="clear")
    result = corridor_result([], verified=True, status="NATIVE_STATE_VERIFIED", requests=4)
    result.pop("built_ops")
    result["phase"]["completed"] = []
    root = write_attempt(tmp_path / "a", prelaunch, result)
    attempt = _load(root)
    assert attempt.derived["requests_per_verified_op"] is None


def test_cli_subcommand_exit_codes(tmp_path: Path):
    root = write_attempt(
        tmp_path / "a",
        corridor_prelaunch(),
        corridor_result(six_receipts(), halt_label="op-06", halt_error="x"),
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.experiments.cli",
            "analyze-native-attempts",
            str(root),
            "--output",
            str(tmp_path / "cliout"),
        ],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["attempts"] == 1
    assert payload["partial_or_failed_outcomes"] == 1
    assert (tmp_path / "cliout" / "execution-metrics.json").exists()
    broken = tmp_path / "bad"
    broken.mkdir()
    (broken / "PRELAUNCH.json").write_bytes(b"{not json")
    bad_run = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.experiments.cli",
            "analyze-native-attempts",
            str(broken),
            "--output",
            str(tmp_path / "cliout2"),
        ],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
    )
    assert bad_run.returncode == 1
    assert "analysis rejected" in bad_run.stderr
    assert not (tmp_path / "cliout2").exists()


RETAINED_D4 = (
    "d4-corridor-native-candidate-1",
    "d4-corridor-native-candidate-3",
    "d4-corridor-native-candidate-4",
)


@pytest.mark.skipif(
    all(not (Path("artifacts/experiments") / name).is_dir() for name in RETAINED_D4),
    reason="retained D4 candidate directories unavailable",
)
class TestRetainedEvidence:
    """Read-only regression over the retained native attempt records."""

    BASE = Path("artifacts/experiments")

    def retained(self, name: str) -> Path:
        return self.BASE / name

    def test_d4_lineage_static_facts(self):
        attempts = tuple(_load(self.retained(name)) for name in RETAINED_D4)
        document = build_analytics_document(attempts)
        by_id = {attempt.attempt_id: attempt for attempt in document.attempts}
        assert by_id["D4-CORRIDOR-1"].record_status.status == "PHASE_HALTED_PREFIX_PRESERVED"
        assert by_id["D4-CORRIDOR-3"].record_status.status == "FAILED_CLEANUP"
        assert by_id["D4-CORRIDOR-4"].record_status.status == "PHASE_HALTED_PREFIX_PRESERVED"
        assert [attempt.record_status.verified for attempt in attempts] == [False, False, False]
        assert document.counts["verified_outcomes"] == 0
        assert document.counts["partial_or_failed_outcomes"] == 3
        candidate1, candidate3, candidate4 = attempts
        assert candidate1.planned.ops == 6
        assert candidate1.planned.longest_run_tiles == 17
        assert candidate1.derived["receipt_backed_ops"] == 1
        assert candidate1.derived["evidence_prefix_fraction"] == pytest.approx(0.1667)
        assert candidate1.derived["op_cost_total"] == 785
        assert candidate1.derived["requests_utilization"] == pytest.approx(0.16)
        assert candidate1.record_status.halt_label == "op-01"
        assert candidate3.planned.ops == 8
        assert candidate3.planned.schedule_version == 2
        assert candidate3.derived["receipt_backed_ops"] == 3
        assert candidate3.derived["evidence_prefix_fraction"] == pytest.approx(0.375)
        assert candidate3.derived["op_cost_total"] == 785 + 1398 + 1151
        assert candidate3.derived["mean_op_cost"] == pytest.approx(1111.33)
        assert candidate3.record_status.halt_label == "op-03"
        assert candidate4.planned.ops == 7
        assert candidate4.planned.schedule_version == 3
        assert candidate4.derived["receipt_backed_ops"] == 6
        assert candidate4.derived["evidence_prefix_fraction"] == pytest.approx(0.8571)
        assert candidate4.derived["op_cost_total"] == 4004
        assert candidate4.record_status.halt_label == "op-06"
        assert "MalformedMessage" in candidate4.record_status.halt_error
        assert candidate4.executed.dispatch_state == "DISPATCHED_UNKNOWN"
        assert candidate4.cleanup.certification == "PASS"
        assert candidate3.cleanup.certification == "NOT_PASS"
        assert candidate3.cleanup.sockets_closed is None
        assert candidate1.cleanup.certification == "PASS"
        lineage = document.lineages[0]
        assert lineage.group == "D4-CONSTRUCTION"
        assert lineage.attempt_names == ("D4-CORRIDOR-1", "D4-CORRIDOR-3", "D4-CORRIDOR-4")
        codes = [observation.code for observation in lineage.observations]
        assert "SCHEDULE_REVISED" in codes
        assert "DESCRIPTIVE_EVIDENCE_PREFIX_SEQUENCE" in codes
        assert "HALT_SURFACES" in codes
        assert "INSUFFICIENT_ATTEMPTS" not in codes
        revisions = lineage.comparisons
        assert revisions[0].from_halt_label == "op-01"
        assert revisions[0].to_halt_label == "op-03"
        assert revisions[1].from_halt_label == "op-03"
        assert revisions[1].to_halt_label == "op-06"
        assert revisions[0].longest_run_change == -8
        assert revisions[1].planned_ops_change == -1
        assert revisions[1].requests_budget_change == -3
        assert revisions[1].receipt_backed_ops_change == 3

    def test_d4_shared_source_world(self):
        worlds = {_load(self.retained(name)).source_world_sha256 for name in RETAINED_D4}
        assert worlds == {"fbebef54dd466e0bea23cc30e11e94ebaf2a3ca07e2e9b7aadd6a6645c37d59e"}

    def test_d3_terraform_complete_attempt(self):
        attempt = _load(self.retained("d3-terraform-native-candidate-1"))
        assert attempt.record_status.status == "NATIVE_TERRAFORM_VERIFIED"
        assert attempt.record_status.verified is True
        assert attempt.planned.ops == 16
        assert attempt.derived["receipt_backed_ops"] == 16
        assert attempt.derived["success_ops"] == 16
        assert attempt.derived["evidence_prefix_fraction"] == pytest.approx(1.0)
        assert attempt.derived["planned_ops_without_evidence"] == 0
        assert attempt.derived["op_cost_total"] == 3382
        assert attempt.derived["requests_utilization"] == pytest.approx(0.9474)
        assert attempt.executed.dispatch_state == "CONFIRMED"
        assert attempt.record_status.verification == "PHASE_COMPLETE"
        assert attempt.cleanup.certification == "PASS"

    def test_d2_d3_clearing_costs(self):
        d2 = _load(self.retained("d2-clearing-native-candidate-3"))
        d3a = _load(self.retained("d3-clearing-native-candidate-1"))
        d3b = _load(self.retained("d3-clearing-native-candidate-2"))
        costs = [attempt.executed.clearing_command_cost for attempt in (d2, d3a, d3b)]
        funds = [attempt.executed.funds_at_exec for attempt in (d2, d3a, d3b)]
        assert costs == [15, 30, 45]
        assert funds == [499985, 499970, 499925]
        assert d2.source_world_sha256 != d3b.source_world_sha256
        document = build_analytics_document((d3a, d3b))
        codes = [observation.code for observation in document.lineages[0].observations]
        assert codes == ["UNRELATED_SOURCE_WORLDS"]
        for attempt in (d2, d3a, d3b):
            assert attempt.cleanup.certification == "PASS"
            assert attempt.record_status.verification == "NATIVE_STATE_VERIFIED"
