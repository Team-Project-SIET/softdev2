"""T01 public domain contracts; no live runtime or external simulator needed."""

import pytest
from pydantic import ValidationError

from app.experiments import domain


def test_live_options_are_optional_inert_and_have_bounded_defaults() -> None:
    options = domain.LiveExecutionOptions()
    assert options.startup_timeout_seconds == 120
    assert options.handshake_timeout_seconds == 10
    assert options.running_timeout_seconds is None
    assert options.shutdown_timeout_seconds == 15
    assert options.terminate_timeout_seconds == options.kill_timeout_seconds == 5
    assert options.final_parse_timeout_seconds == options.final_flush_timeout_seconds == 30
    assert options.reconnect_budget_seconds == 15
    assert options.heartbeat_interval_seconds == 5
    assert options.heartbeat_timeout_seconds == 15
    assert options.persistence_retry_budget_seconds == 10
    assert options.persistence_flush_interval_seconds == 1
    assert options.persistence_batch_size == 100
    assert options.persistence_queue_capacity == 1024
    assert domain.LiveExecutionOptions.model_validate_json(options.model_dump_json()) == options


@pytest.mark.parametrize(
    "values",
    [
        {"startup_timeout_seconds": 0},
        {"handshake_timeout_seconds": -1},
        {"running_timeout_seconds": float("inf")},
        {"shutdown_timeout_seconds": float("nan")},
        {"reconnect_budget_seconds": True},
        {"persistence_batch_size": 0},
        {"persistence_queue_capacity": 1.5},
        {"persistence_batch_size": 1025},
        {"heartbeat_timeout_seconds": 4},
        {"startup_timout_seconds": 120},
    ],
)
def test_invalid_live_options_are_rejected(values: dict) -> None:
    with pytest.raises(ValidationError):
        domain.LiveExecutionOptions.model_validate(values)


def experiment_payload() -> dict:
    return {
        "run_id": 1,
        "config": {
            "scenario": {"identifier": "map", "version": "1"},
            "planning": {"strategy_identifier": "baseline", "strategy_version": "1"},
            "ai": {
                "content_id": "54524149",
                "name": "trAIns",
                "md5": "c4c069dc797674e545411b59867ad0c2",
            },
            "openttd_version": "13.4",
            "opengfx_version": "7.1",
            "seed": 17,
            "duration_days": 120,
        },
        "status": "succeeded",
        "started_at": "2026-09-25T00:00:00Z",
        "simulation": {
            "simulation_date": "1950-05-01",
            "savegame_version": 302,
            "metrics": [{"name": "current_period_expenses", "value": -390, "unit": "GBP"}],
        },
    }


def test_live_summary_round_trips_without_changing_economic_metrics() -> None:
    summary = {
        "telemetry_status": "incomplete",
        "coverage_started_at": "2026-09-25T00:00:01Z",
        "coverage_ended_at": "2026-09-25T00:04:37Z",
        "received_count": 134,
        "persisted_count": 134,
        "gap_count": 1,
        "dropped_count": 0,
        "last_sequence": 134,
        "last_observed_day": 712343,
        "process_exit_code": 0,
        "requested_target_day": 712343,
        "actual_final_day": 712344,
        "raw_save_reference": "run-1/final.sav",
        "parsed_artifact_reference": "run-1/experiment-1.json.gz",
        "outcome_manifest_reference": "run-1/outcome.json",
        "cleanup_succeeded": True,
    }
    payload = experiment_payload()
    payload.update(execution_mode="live", live_summary=summary)
    payload["simulation"]["live_summary"] = summary
    result = domain.ExperimentResult.model_validate(payload)
    assert result.execution_mode is domain.ExecutionMode.LIVE
    assert result.live_summary is not None and result.simulation is not None
    assert result.live_summary.telemetry_status is domain.TelemetryStatus.INCOMPLETE
    assert result.simulation.live_summary == result.live_summary
    assert result.simulation.metrics[0].value == -390
    assert result.model_dump(mode="json")["execution_mode"] == "live"
    assert domain.ExperimentResult.model_validate_json(result.model_dump_json()) == result


def test_typed_execution_failure_carries_context_without_changing_run_statuses() -> None:
    failure = domain.ExecutionFailure.model_validate(
        {
            "code": "timeout",
            "message": "Simulation exceeded its running deadline",
            "partial_artifact_reference": "run-1/partial.sav",
            "last_observed_day": 712300,
            "process_exit_code": -15,
            "cleanup_diagnostics": ["Process group reaped"],
            "live_summary": {"telemetry_status": "failed", "cleanup_succeeded": True},
        }
    )
    error = domain.SimulationExecutionError(failure)
    assert error.failure.code is domain.ExecutionFailureCode.TIMEOUT
    assert str(error) == "Simulation exceeded its running deadline"
    assert domain.ExecutionFailure.model_validate_json(failure.model_dump_json()) == failure
    payload = experiment_payload()
    payload.update(
        execution_mode="live",
        status="failed",
        simulation=None,
        failure_code=failure.code,
        error=str(error),
        live_summary=failure.live_summary,
    )
    result = domain.ExperimentResult.model_validate(payload)
    assert domain.ExperimentResult.model_validate_json(result.model_dump_json()) == result
    assert set(domain.RunStatus) == {"running", "succeeded", "failed"}


@pytest.mark.parametrize(
    "changes",
    [
        {"execution_mode": "dedicated"},
        {"failure_code": "made_up"},
        {"live_summary": {"telemetry_status": "lost"}},
    ],
)
def test_invalid_execution_metadata_is_rejected(changes: dict) -> None:
    with pytest.raises(ValidationError):
        domain.ExperimentResult.model_validate(experiment_payload() | changes)


def test_invalid_failure_code_is_rejected() -> None:
    with pytest.raises(ValidationError):
        domain.ExecutionFailure.model_validate({"code": "completion", "message": "not a failure"})


def test_legacy_batch_dump_and_nested_exports_keep_their_original_shape() -> None:
    import json

    from pydantic import BaseModel

    class Export(BaseModel):
        runs: tuple[domain.ExperimentResult, ...]

    result = domain.ExperimentResult.model_validate(experiment_payload())
    dumped = json.loads(result.model_dump_json())
    assert set(dumped) == {
        "run_id",
        "config",
        "status",
        "started_at",
        "completed_at",
        "simulation",
        "error",
    }
    assert dumped["error"] is None and dumped["completed_at"] is None
    assert dumped["simulation"] == {
        "simulation_date": "1950-05-01",
        "savegame_version": 302,
        "metrics": [{"name": "current_period_expenses", "value": -390.0, "unit": "GBP"}],
        "raw_artifact_reference": None,
    }
    assert json.loads(Export(runs=(result,)).model_dump_json()) == {"runs": [dumped]}
    assert (
        domain.ExperimentResult.model_validate(dumped).execution_mode is domain.ExecutionMode.BATCH
    )
    assert result.model_dump(include={"execution_mode", "live_summary", "failure_code"}) == {}
    assert result.simulation is not None
    assert result.simulation.model_dump(include={"live_summary"}) == {}


def test_domain_import_and_metadata_construction_do_not_start_runtime_work() -> None:
    import subprocess
    import sys

    # A fresh interpreter catches import-time side effects too. No OpenTTD is started.
    script = """
import sys

def deny_runtime(event, args):
    if event.startswith("socket.") or event in {
        "subprocess.Popen", "os.fork", "os.posix_spawn", "os.system"
    }:
        raise AssertionError(event)

sys.addaudithook(deny_runtime)
from app.experiments.domain import LiveExecutionOptions, LiveExecutionSummary, ExecutionFailure
LiveExecutionOptions()
LiveExecutionSummary(telemetry_status="pending")
ExecutionFailure(code="timeout", message="safe test message")
assert "openttdlab" not in sys.modules
assert not any(name.startswith("prototype.live_admin") for name in sys.modules)
"""
    completed = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


def test_result_serialization_schema_still_describes_legacy_fields() -> None:
    simulation_schema = domain.SimulationResult.model_json_schema(mode="serialization")
    assert simulation_schema["required"] == ["simulation_date", "savegame_version", "metrics"]
    assert {"simulation_date", "savegame_version", "metrics", "raw_artifact_reference"} <= set(
        simulation_schema["properties"]
    )
    experiment_schema = domain.ExperimentResult.model_json_schema(mode="serialization")
    assert experiment_schema["required"] == ["run_id", "config", "status", "started_at"]
    assert {"simulation", "error", "completed_at"} <= set(experiment_schema["properties"])
