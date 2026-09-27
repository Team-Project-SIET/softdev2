"""The argparse command delegates one typed result without starting a simulator."""

import signal
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from app.experiments import cli
from app.experiments.domain import (
    ExecutionFailureCode,
    ExecutionMode,
    ExperimentConfig,
    ExperimentResult,
    LiveExecutionSummary,
    Metric,
    RunStatus,
    SimulationResult,
    TelemetryStatus,
)
from app.experiments.outcome_recovery import RecoveryResult, RecoveryStatus


class RecordingService:
    def __init__(
        self,
        *,
        status: RunStatus = RunStatus.SUCCEEDED,
        telemetry_status: TelemetryStatus | None = None,
        failure_code: ExecutionFailureCode | None = None,
        include_error: bool = True,
        terminal_persistence_failed: bool = False,
        outcome_manifest_failed: bool = False,
    ) -> None:
        self.status = status
        self.telemetry_status = telemetry_status
        self.failure_code = failure_code
        self.include_error = include_error
        self.terminal_persistence_failed = terminal_persistence_failed
        self.outcome_manifest_failed = outcome_manifest_failed
        self.calls: list[tuple[ExperimentConfig, Path, ExecutionMode]] = []

    def run(
        self,
        config: ExperimentConfig,
        *,
        artifact_dir: Path,
        execution_mode: ExecutionMode = ExecutionMode.BATCH,
    ) -> ExperimentResult:
        self.calls.append((config, artifact_dir, execution_mode))
        summary = (
            LiveExecutionSummary(
                telemetry_status=self.telemetry_status,
                requested_target_day=712953,
                last_observed_day=712954,
                actual_final_day=712955,
                raw_save_reference="run-7/final.sav",
                parsed_artifact_reference="run-7/parsed.json.gz",
                cleanup_diagnostics=("admin_password=do-not-print",),
            )
            if self.telemetry_status is not None
            else None
        )

        simulation = (
            SimulationResult(
                simulation_date=date(1951, 1, 2),
                savegame_version=302,
                metrics=(Metric(name="company_money", value=123, unit="GBP"),),
                raw_artifact_reference="run-7/parsed.json.gz",
                live_summary=summary,
            )
            if self.status is RunStatus.SUCCEEDED
            else None
        )
        return ExperimentResult(
            run_id=7,
            config=config,
            status=self.status,
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
            completed_at=datetime(2026, 1, 1, tzinfo=UTC),
            simulation=simulation,
            error=(
                "finalization failure"
                if self.status is RunStatus.FAILED and self.include_error
                else None
            ),
            execution_mode=execution_mode,
            failure_code=self.failure_code,
            live_summary=summary,
            terminal_persistence_failed=self.terminal_persistence_failed,
            outcome_manifest_failed=self.outcome_manifest_failed,
        )


@pytest.mark.parametrize(
    ("status", "expected_exit"),
    [
        (RecoveryStatus.RECOVERED, 0),
        (RecoveryStatus.ALREADY_RECONCILED, 0),
        (RecoveryStatus.INVALID_MANIFEST, 1),
        (RecoveryStatus.CONFLICT, 1),
    ],
)
def test_recover_command_uses_only_recovery_service(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    status: RecoveryStatus,
    expected_exit: int,
) -> None:
    calls: list[tuple[Path, Path]] = []

    class Recovery:
        def recover(self, root: Path, manifest: Path) -> RecoveryResult:
            calls.append((root, manifest))
            return RecoveryResult(status=status, run_id=7)

    monkeypatch.setattr(cli, "OutcomeRecoveryService", Recovery)
    monkeypatch.setattr(
        cli, "ExperimentService", lambda **kwargs: (_ for _ in ()).throw(AssertionError("run"))
    )
    manifest = tmp_path / "run-7/outcome-v1.json"
    assert cli.main(["recover", str(manifest), "--artifact-dir", str(tmp_path)]) == expected_exit
    assert calls == [(tmp_path, manifest)]
    assert capsys.readouterr().out == f"recovery={status} run=7\n"


@pytest.mark.parametrize(
    ("mode_args", "expected_mode"),
    [
        ([], ExecutionMode.BATCH),
        (["--mode", "batch"], ExecutionMode.BATCH),
        (["--mode", "live"], ExecutionMode.LIVE),
    ],
)
def test_run_mode_delegates_once_with_existing_config(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    mode_args: list[str],
    expected_mode: ExecutionMode,
) -> None:
    service = RecordingService(
        telemetry_status=TelemetryStatus.COMPLETE if expected_mode is ExecutionMode.LIVE else None
    )
    monkeypatch.setattr(cli, "ExperimentService", lambda **_kwargs: service)
    destination = tmp_path / "artifacts"
    exit_code = cli.main(
        ["run", *mode_args, "--seed", "23", "--days", "90", "--artifact-dir", str(destination)]
    )
    assert exit_code == 0
    assert len(service.calls) == 1
    config, artifact_dir, mode = service.calls[0]
    assert config.seed == 23 and config.duration_days == 90
    assert artifact_dir == destination
    assert mode is expected_mode
    output = capsys.readouterr().out
    assert "company_money=123.0 GBP" in output
    if mode is ExecutionMode.BATCH:
        assert "run=7 status=succeeded\n" in output
        assert "raw_artifact=run-7/parsed.json.gz" in output
        assert "telemetry=" not in output and "mode=" not in output
    else:
        assert "run=7 mode=live status=succeeded telemetry=complete" in output


@pytest.mark.parametrize(
    "args",
    [
        ["run", "--mode", "unknown"],
        ["compare", "--mode", "live", "--strategies", "road-only,multimodal", "--seeds", "0:1"],
    ],
)
def test_argparse_rejects_invalid_or_compare_live_mode(
    monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    monkeypatch.setattr(cli, "ExperimentService", lambda: pytest.fail("must not construct service"))
    with pytest.raises(SystemExit) as error:
        cli.main(args)
    assert error.value.code == 2


def test_compare_still_invokes_only_batch_runs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    service = RecordingService()
    monkeypatch.setattr(cli, "ExperimentService", lambda **_kwargs: service)
    exit_code = cli.main(
        [
            "compare",
            "--strategies",
            "road-only,multimodal",
            "--seeds",
            "0:1",
            "--artifact-dir",
            str(tmp_path),
        ]
    )
    assert exit_code == 0
    assert len(service.calls) == 2
    assert all(mode is ExecutionMode.BATCH for _, _, mode in service.calls)
    output = capsys.readouterr().out
    assert "summary strategy=" in output
    assert "mode=live" not in output


def test_live_incomplete_is_success_with_exit_three(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    service = RecordingService(telemetry_status=TelemetryStatus.INCOMPLETE)
    monkeypatch.setattr(cli, "ExperimentService", lambda **_kwargs: service)
    assert cli.main(["run", "--mode", "live", "--artifact-dir", str(tmp_path)]) == 3
    output = capsys.readouterr().out
    assert "run=7 mode=live status=succeeded telemetry=incomplete" in output
    assert "simulation_date=1951-01-02" in output
    assert "requested_target_day=712953" in output
    assert "last_observed_day=712954" in output
    assert "actual_final_day=712955" in output
    assert "company_money=123.0 GBP" in output
    assert "raw_save=run-7/final.sav" in output
    assert "parsed_artifact=run-7/parsed.json.gz" in output
    assert "status=failed" not in output


@pytest.mark.parametrize(
    ("received_signal", "expected_exit"),
    [(signal.SIGINT, 130), (signal.SIGTERM, 143)],
)
def test_catchable_live_signal_sets_runner_token_and_restores_handlers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    received_signal: signal.Signals,
    expected_exit: int,
) -> None:
    from app.experiments.cancellation import LiveCancellation

    service = RecordingService(
        status=RunStatus.FAILED,
        telemetry_status=TelemetryStatus.FAILED,
        failure_code=ExecutionFailureCode.CANCELLED,
    )
    requests: list[LiveCancellation] = []

    def construct(*, live_cancellation: LiveCancellation) -> RecordingService:
        requests.append(live_cancellation)
        original_run = service.run

        def run(
            config: ExperimentConfig,
            *,
            artifact_dir: Path,
            execution_mode: ExecutionMode = ExecutionMode.BATCH,
        ) -> ExperimentResult:
            signal.raise_signal(received_signal)
            return original_run(config, artifact_dir=artifact_dir, execution_mode=execution_mode)

        service.run = run
        return service

    previous_int = signal.getsignal(signal.SIGINT)
    previous_term = signal.getsignal(signal.SIGTERM)
    monkeypatch.setattr(cli, "ExperimentService", construct)
    assert cli.main(["run", "--mode", "live", "--artifact-dir", str(tmp_path)]) == expected_exit
    assert requests[0].event.is_set()
    assert requests[0].signal_name == received_signal.name
    assert signal.getsignal(signal.SIGINT) == previous_int
    assert signal.getsignal(signal.SIGTERM) == previous_term
    assert len(service.calls) == 1


def test_batch_failure_keeps_simple_output_and_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    service = RecordingService(status=RunStatus.FAILED)
    monkeypatch.setattr(cli, "ExperimentService", lambda **_kwargs: service)
    assert cli.main(["run", "--artifact-dir", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert captured.out == "run=7 status=failed\n"
    assert captured.err == "finalization failure\n"
    assert len(service.calls) == 1


@pytest.mark.parametrize(
    ("code", "expected_exit"),
    [
        (ExecutionFailureCode.TIMEOUT, 124),
        (ExecutionFailureCode.CANCELLED, 130),
        (ExecutionFailureCode.FINALIZATION_FAILURE, 1),
        (None, 1),
    ],
)
def test_live_failure_prints_only_sanitized_result_fields(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    code: ExecutionFailureCode | None,
    expected_exit: int,
) -> None:
    service = RecordingService(
        status=RunStatus.FAILED,
        telemetry_status=TelemetryStatus.FAILED,
        failure_code=code,
    )
    monkeypatch.setattr(cli, "ExperimentService", lambda **_kwargs: service)
    assert cli.main(["run", "--mode", "live", "--artifact-dir", str(tmp_path)]) == expected_exit
    assert len(service.calls) == 1
    captured = capsys.readouterr()
    assert "run=7 mode=live status=failed telemetry=failed" in captured.out
    if code is None:
        assert "failure_code=" not in captured.out
    else:
        assert f"failure_code={code.value}" in captured.out
    assert "error=finalization failure" in captured.out
    for forbidden in ("password", "secrets.cfg", "argv", "execution_metadata", "Traceback"):
        assert forbidden not in captured.out + captured.err
    assert "raw_save_sha256" not in captured.out
    assert "cleanup_diagnostics" not in captured.out


def test_live_failure_code_prints_without_error_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    service = RecordingService(
        status=RunStatus.FAILED,
        telemetry_status=TelemetryStatus.FAILED,
        failure_code=ExecutionFailureCode.PROTOCOL_FAILURE,
        include_error=False,
    )
    monkeypatch.setattr(cli, "ExperimentService", lambda **_kwargs: service)
    assert cli.main(["run", "--mode", "live", "--artifact-dir", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert "failure_code=protocol_failure" in output
    assert "error=" not in output


@pytest.mark.parametrize(
    ("status", "code", "terminal_failed", "manifest_failed", "expected_exit"),
    [
        (RunStatus.FAILED, ExecutionFailureCode.TIMEOUT, True, False, 1),
        (RunStatus.FAILED, ExecutionFailureCode.CANCELLED, True, False, 1),
        (RunStatus.FAILED, ExecutionFailureCode.TIMEOUT, False, True, 124),
        (RunStatus.FAILED, ExecutionFailureCode.CANCELLED, False, True, 130),
        (RunStatus.SUCCEEDED, None, False, True, 1),
    ],
)
def test_live_outcome_evidence_failure_exits_one(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    status: RunStatus,
    code: ExecutionFailureCode | None,
    terminal_failed: bool,
    manifest_failed: bool,
    expected_exit: int,
) -> None:
    service = RecordingService(
        status=status,
        telemetry_status=TelemetryStatus.FAILED,
        failure_code=code,
        terminal_persistence_failed=terminal_failed,
        outcome_manifest_failed=manifest_failed,
    )
    monkeypatch.setattr(cli, "ExperimentService", lambda **_kwargs: service)
    assert cli.main(["run", "--mode", "live", "--artifact-dir", str(tmp_path)]) == expected_exit
