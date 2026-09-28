"""Opt-in T17 proof of one real production live simulation in an isolated schema."""

import asyncio
import hashlib
import json
import os
import signal
import sys
import threading
from datetime import date
from pathlib import Path

import pytest
from alembic.config import Config
from port_release_probe import PortReleaseError, verify_port_release
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from test_postgres_integration import _upgrade_isolated
from test_postgres_integration import postgres_factory as postgres_factory

from app.config import get_settings
from app.experiments import cli
from app.experiments.domain import ExecutionMode, RunStatus, TelemetryStatus
from app.experiments.model import (
    ExperimentMetricRecord,
    ExperimentRunRecord,
    LiveTelemetrySessionRecord,
    SimulationRunRecord,
    TelemetryObservationRecord,
)
from app.experiments.outcome_manifest import OutcomeManifest
from app.experiments.service import ExperimentService
from app.experiments.telemetry_repository import NegotiatedSubscriptions, TelemetryRepository
from app.simulation.openttd.admin_observer import AdminObserver, ObserverHealth, ObserverState
from app.simulation.openttd.live_launch import LiveLaunchPreparation, PreparedLiveRuntime
from app.simulation.openttd.live_runner import _SaveWaiter
from app.simulation.openttd.telemetry import ObservationKind, supported_game_day_to_date


@pytest.mark.openttd
def test_one_real_production_live_run(
    request: pytest.FixtureRequest,
    postgres_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    if not request.config.getoption("--run-openttd"):
        pytest.skip("pass --run-openttd and --run-postgres for the single T17 smoke")
    artifact_value = os.environ.get("T17_ARTIFACT_ROOT")
    if artifact_value is None:
        pytest.fail("T17_ARTIFACT_ROOT must identify the preflighted dedicated artifact root")
    artifact_root = Path(artifact_value)
    assert artifact_root.is_absolute() and artifact_root.is_dir() and not artifact_root.is_symlink()
    assert not list(artifact_root.glob("run-*"))
    assert (artifact_root / ".live-runtime-cache/openttd-13.4-pinned-v1").is_dir()

    engine = postgres_factory.kw["bind"]
    migrations = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    migrations.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "alembic")
    )
    _upgrade_isolated(migrations, engine, "head")
    with postgres_factory() as session:
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == "0007"
        schema = session.scalar(text("SELECT current_schema()"))
    scoped_url = engine.url.update_query_dict({"options": f"-c search_path={schema}"})

    spawned: list[tuple[str, int]] = []
    ports: list[tuple[int, int]] = []
    workspaces: list[Path] = []
    prepared_handles: list[PreparedLiveRuntime] = []
    passwords: list[str] = []
    stores: list[TelemetryRepository] = []
    tasks: list[asyncio.Task[object]] = []
    save_events: list[str] = []
    original_spawn = asyncio.create_subprocess_exec
    original_prepare = LiveLaunchPreparation.prepare
    original_create_task = asyncio.create_task
    original_feed_line = _SaveWaiter.feed_line
    original_observer_run = AdminObserver.run
    connected_epoch = 0
    ready_epochs: list[tuple[int, NegotiatedSubscriptions]] = []
    signal_handlers = {
        number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)
    }

    async def record_spawn(*args, **kwargs):
        child = await original_spawn(*args, **kwargs)
        kind = "parser" if args[3] == sys.executable else "world"
        spawned.append((kind, child.pid))
        return child

    def record_prepare(self, config, runtime, **kwargs):
        prepared = original_prepare(self, config, runtime, **kwargs)
        ports.append((prepared.game_port, prepared.admin_port))
        workspaces.append(prepared.workspace)
        prepared_handles.append(prepared)
        passwords.append(prepared.admin_password)
        return prepared

    def record_task(coroutine, *args, **kwargs):
        task = original_create_task(coroutine, *args, **kwargs)
        tasks.append(task)
        return task

    def record_save_line(self, line):
        started_before = self.started.done()
        terminal_before = self.terminal.done()
        original_feed_line(self, line)
        if not started_before and self.started.done():
            save_events.append("Saving map...")
        if not terminal_before and self.terminal.done():
            save_events.append("saved" if self.terminal.result() else "failed")

    async def record_observer_run(self, emit):
        def record_event(event):
            nonlocal connected_epoch
            if isinstance(event, ObserverHealth):
                if event.state is ObserverState.CONNECTED:
                    connected_epoch += 1
                elif event.state is ObserverState.READY:
                    assert event.subscriptions is not None
                    ready_epochs.append(
                        (
                            connected_epoch,
                            NegotiatedSubscriptions.model_validate(
                                {
                                    "connection_epoch": connected_epoch,
                                    "subscriptions": [
                                        {
                                            "update_type": kind.name.lower(),
                                            "frequency": frequency.name.lower(),
                                        }
                                        for kind, frequency in event.subscriptions
                                    ],
                                }
                            ),
                        )
                    )
            return emit(event)

        await original_observer_run(self, record_event)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", record_spawn)
    monkeypatch.setattr(asyncio, "create_task", record_task)
    monkeypatch.setattr(LiveLaunchPreparation, "prepare", record_prepare)
    monkeypatch.setattr(_SaveWaiter, "feed_line", record_save_line)
    monkeypatch.setattr(AdminObserver, "run", record_observer_run)

    def telemetry_store() -> TelemetryRepository:
        store = TelemetryRepository(scoped_url)
        stores.append(store)
        return store

    def production_service(**kwargs) -> ExperimentService:
        return ExperimentService(
            postgres_factory,
            telemetry_store_factory=telemetry_store,
            live_cancellation=kwargs.get("live_cancellation"),
        )

    monkeypatch.setattr(cli, "ExperimentService", production_service)
    monitor_stop = threading.Event()
    live_kinds: set[str] = set()
    live_days: set[int] = set()
    live_cash: set[int] = set()
    live_quarter_days: set[int] = set()
    monitor_errors: list[str] = []

    def observe_while_running() -> None:
        while not monitor_stop.wait(0.2):
            world_pids = [pid for kind, pid in spawned if kind == "world"]
            if not world_pids or not Path(f"/proc/{world_pids[0]}").exists():
                continue
            try:
                with postgres_factory() as session:
                    run = session.scalar(
                        select(ExperimentRunRecord)
                        .where(ExperimentRunRecord.execution_mode == ExecutionMode.LIVE)
                        .order_by(ExperimentRunRecord.id.desc())
                    )
                    if run is None or run.status != RunStatus.RUNNING:
                        continue
                    observations = session.scalars(
                        select(TelemetryObservationRecord).where(
                            TelemetryObservationRecord.experiment_run_id == run.id
                        )
                    ).all()
                    for item in observations:
                        live_kinds.add(item.kind)
                        if item.kind == ObservationKind.DATE and item.game_day is not None:
                            live_days.add(item.game_day)
                        if item.kind == ObservationKind.COMPANY_ECONOMY:
                            live_cash.add(item.payload["cash_balance_gbp"])
                            if len(item.payload["completed_quarters"]) == 2 and item.game_day:
                                live_quarter_days.add(item.game_day)
            except Exception as exc:
                monitor_errors.append(type(exc).__name__)
                return

    monitor = threading.Thread(target=observe_while_running, daemon=True)
    monitor.start()
    try:
        exit_code = cli.main(
            [
                "run",
                "--mode",
                "live",
                "--strategy",
                "road-only",
                "--seed",
                "17",
                "--days",
                "120",
                "--artifact-dir",
                str(artifact_root),
            ]
        )
    finally:
        monitor_stop.set()
        monitor.join(5)
    output = capsys.readouterr()
    (artifact_root / "smoke-observed.json").write_text(
        json.dumps(
            {
                "phase": "production_command_returned",
                "cli_exit": exit_code,
                "world_count": sum(kind == "world" for kind, _ in spawned),
                "parser_count": sum(kind == "parser" for kind, _ in spawned),
                "save_events": save_events,
                "ports": ports,
                "workspace_removed": not any(workspace.exists() for workspace in workspaces),
                "stores_closed": all(store._closed for store in stores),
                "monitor_errors": monitor_errors,
                "ready_epochs": [epoch for epoch, _ in ready_epochs],
            },
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    assert not monitor.is_alive() and not monitor_errors
    assert [kind for kind, _ in spawned].count("world") == 1
    assert [kind for kind, _ in spawned].count("parser") == 1
    assert save_events == ["Saving map...", "saved"]
    assert len(ports) == len(workspaces) == len(passwords) == 1
    assert len(stores) == 1 and stores[0]._closed
    if exit_code not in {0, 3}:
        with postgres_factory() as session:
            failed_run = session.scalar(select(ExperimentRunRecord))
            failed_live = (
                session.get(LiveTelemetrySessionRecord, failed_run.id)
                if failed_run is not None
                else None
            )
            failure_evidence = {
                "cli_exit": exit_code,
                "run_id": failed_run.id if failed_run is not None else None,
                "db_status": str(failed_run.status) if failed_run is not None else None,
                "db_failure_code": (
                    str(failed_run.failure_code)
                    if failed_run is not None and failed_run.failure_code is not None
                    else None
                ),
                "simulation_row_present": (
                    failed_run.simulation is not None if failed_run is not None else False
                ),
                "telemetry_status": (
                    str(failed_live.telemetry_status) if failed_live is not None else None
                ),
                "telemetry_persisted_count": (
                    failed_live.persisted_count if failed_live is not None else None
                ),
                "world_count": sum(kind == "world" for kind, _ in spawned),
                "parser_count": sum(kind == "parser" for kind, _ in spawned),
                "workspace_removed": not any(workspace.exists() for workspace in workspaces),
                "manifest_present": (
                    (artifact_root / f"run-{failed_run.id}/outcome-v1.json").exists()
                    if failed_run is not None
                    else False
                ),
            }
        (artifact_root / "smoke-failure-evidence.json").write_text(
            json.dumps(failure_evidence, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
    assert exit_code in {0, 3}
    assert "mode=live status=succeeded" in output.out
    required = {
        ObservationKind.DATE,
        ObservationKind.COMPANY_INFO,
        ObservationKind.COMPANY_ECONOMY,
        ObservationKind.COMPANY_STATS,
    }
    assert required <= live_kinds
    assert len(live_days) >= 2 and len(live_cash) >= 2
    first_date = supported_game_day_to_date(min(live_days))
    first_quarter = (first_date.year, (first_date.month - 1) // 3)
    assert any(
        (
            supported_game_day_to_date(day).year,
            (supported_game_day_to_date(day).month - 1) // 3,
        )
        > first_quarter
        for day in live_quarter_days
    )

    with postgres_factory() as session:
        runs = session.scalars(select(ExperimentRunRecord)).all()
        assert len(runs) == 1
        run = runs[0]
        assert run.status == RunStatus.SUCCEEDED
        assert run.failure_code is None and run.error is None and run.completed_at is not None
        assert run.execution_mode == ExecutionMode.LIVE
        assert run.strategy.identifier == "simple-road-only"
        assert run.ai_configuration["content_id"] == "534d504c"
        assert run.seed == 17 and run.duration_days == 120
        assert run.openttd_version == "13.4" and run.opengfx_version == "7.1"
        live = session.get(LiveTelemetrySessionRecord, run.id)
        assert live is not None and live.connection_count >= 1
        assert live.protocol_version == 2 and live.connected_at is not None
        (artifact_root / "smoke-db-observed.json").write_text(
            json.dumps(
                {
                    "run_id": run.id,
                    "status": str(run.status),
                    "connection_count": live.connection_count,
                    "received_count": live.received_count,
                    "persisted_count": live.persisted_count,
                    "negotiated_subscriptions": live.negotiated_subscriptions,
                    "ready_epochs": [epoch for epoch, _ in ready_epochs],
                },
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        assert live.ended_at is not None and ready_epochs
        assert live.negotiated_subscriptions is not None
        assert (
            NegotiatedSubscriptions.model_validate(live.negotiated_subscriptions)
            == ready_epochs[-1][1]
        )
        assert ready_epochs[-1][0] <= live.connection_count
        assert live.telemetry_status in {TelemetryStatus.COMPLETE, TelemetryStatus.INCOMPLETE}
        assert exit_code == (0 if live.telemetry_status == TelemetryStatus.COMPLETE else 3)
        observations = session.scalars(
            select(TelemetryObservationRecord)
            .where(TelemetryObservationRecord.experiment_run_id == run.id)
            .order_by(TelemetryObservationRecord.sequence)
        ).all()
        assert required <= {item.kind for item in observations}
        assert [item.sequence for item in observations] == list(range(1, len(observations) + 1))
        assert live.persisted_count == len(observations)
        assert live.received_count >= live.persisted_count > 0
        assert live.gap_count == live.dropped_count == 0
        assert live.final_persisted_sequence == observations[-1].sequence
        assert len(session.scalars(select(SimulationRunRecord)).all()) == 1
        simulation = run.simulation
        assert simulation is not None and simulation.metrics
        assert simulation.experiment_run_id == run.id
        assert len(simulation.metrics) == len({item.name for item in simulation.metrics})
        assert len(session.scalars(select(ExperimentMetricRecord)).all()) == len(simulation.metrics)
        assert run.raw_artifact_reference is not None
        assert simulation.simulation_date >= supported_game_day_to_date(live.last_observed_day)
        assert run.execution_metadata is not None
        persisted_fields = json.dumps(
            {
                "strategy_configuration": run.strategy_configuration,
                "ai_configuration": run.ai_configuration,
                "execution_metadata": run.execution_metadata,
                "error": run.error,
                "artifact_reference": run.raw_artifact_reference,
                "telemetry_subscriptions": live.negotiated_subscriptions,
                "telemetry_payloads": [item.payload for item in observations],
            }
        )
        metrics = {item.name: str(item.value) for item in simulation.metrics}
        run_id = run.id
        summary = {
            "run_id": run_id,
            "cli_exit": exit_code,
            "status": str(run.status),
            "telemetry_status": str(live.telemetry_status),
            "connection_count": live.connection_count,
            "received_count": live.received_count,
            "persisted_count": live.persisted_count,
            "gap_count": live.gap_count,
            "dropped_count": live.dropped_count,
            "last_observed_day": live.last_observed_day,
            "final_persisted_sequence": live.final_persisted_sequence,
            "negotiated_subscriptions": live.negotiated_subscriptions,
            "simulation_date": simulation.simulation_date.isoformat(),
            "savegame_version": simulation.savegame_version,
            "metrics": metrics,
            "ports": ports,
            "world_count": sum(kind == "world" for kind, _ in spawned),
            "parser_count": sum(kind == "parser" for kind, _ in spawned),
        }
    (artifact_root / "smoke-observed.json").write_text(
        json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )

    run_dir = artifact_root / f"run-{run_id}"
    manifest_path = run_dir / "outcome-v1.json"
    manifest = OutcomeManifest.model_validate_json(manifest_path.read_bytes())
    assert manifest.schema_version == 1 and manifest.run_id == run_id
    assert manifest.execution_mode is ExecutionMode.LIVE
    assert manifest.intended_status is RunStatus.SUCCEEDED
    assert manifest.simulation is not None and manifest.live_summary is not None
    assert manifest.live_summary.cleanup_succeeded is True
    assert manifest.live_summary.cleanup_diagnostics == ()
    assert manifest.live_summary.process_exit_code == 0
    assert manifest.live_summary.requested_target_day is not None
    assert live.last_observed_day is not None
    assert live.last_observed_day >= manifest.live_summary.requested_target_day
    assert supported_game_day_to_date(manifest.live_summary.requested_target_day) == date(
        1950, 5, 1
    )
    assert manifest.live_summary.actual_final_day >= manifest.live_summary.requested_target_day
    assert supported_game_day_to_date(manifest.live_summary.actual_final_day) == date.fromisoformat(
        summary["simulation_date"]
    )
    assert manifest.simulation.simulation_date.isoformat() == summary["simulation_date"]
    assert manifest.live_summary.telemetry_status == summary["telemetry_status"]
    raw_reference = manifest.live_summary.raw_save_reference
    parsed_reference = manifest.live_summary.parsed_artifact_reference
    assert raw_reference is not None and parsed_reference is not None
    assert raw_reference == f"run-{run_id}/experiment-{run_id}.sav"
    assert parsed_reference == f"run-{run_id}/experiment-{run_id}.json.gz"
    assert manifest.simulation.raw_artifact_reference == parsed_reference
    assert run.raw_artifact_reference == parsed_reference
    assert manifest.live_summary.received_count == summary["received_count"]
    assert manifest.live_summary.persisted_count == summary["persisted_count"]
    raw = artifact_root / raw_reference
    parsed = artifact_root / parsed_reference
    assert raw.parent == parsed.parent == run_dir
    for path in (raw, parsed):
        assert path.is_file() and not path.is_symlink() and path.stat().st_size > 0
    assert hashlib.sha256(raw.read_bytes()).hexdigest() == manifest.live_summary.raw_save_sha256
    assert (
        hashlib.sha256(parsed.read_bytes()).hexdigest()
        == manifest.live_summary.parsed_artifact_sha256
        == manifest.final_artifact_sha256
    )

    visible_text = output.out + output.err + persisted_fields + manifest_path.read_text()
    for secret in passwords:
        if secret in visible_text:
            pytest.fail("generated Admin password found in visible evidence")
        if secret.encode() in manifest_path.read_bytes() + raw.read_bytes() + parsed.read_bytes():
            pytest.fail("generated Admin password found in owned artifacts")
        if any(secret in path.name for path in run_dir.iterdir()):
            pytest.fail("generated Admin password found in an artifact name")
    db_password = make_url(str(get_settings().database_url)).password
    if db_password is not None and db_password in visible_text:
        pytest.fail("database password found in visible evidence")
    assert all(task.done() for task in tasks)
    assert {number: signal.getsignal(number) for number in signal_handlers} == signal_handlers
    assert not any(workspace.exists() for workspace in workspaces)
    assert all(prepared.lease.closed for prepared in prepared_handles)
    assert not any(Path(f"/proc/{pid}").exists() for _, pid in spawned)
    world_pid = next(pid for kind, pid in spawned if kind == "world")
    for entry in Path("/proc").iterdir():
        if entry.name.isdecimal():
            try:
                fields = (entry / "stat").read_text().rsplit(") ", 1)[1].split()
            except FileNotFoundError, ProcessLookupError:
                continue
            assert int(fields[2]) != world_pid
    game_port, admin_port = ports[0]
    assert game_port != admin_port
    try:
        port_evidence = verify_port_release(
            game_port,
            admin_port,
            owned_pgid=world_pid,
            timeout_seconds=1.0,
            process_checks_passed=True,
        )
    except PortReleaseError as exc:
        (artifact_root / "smoke-port-evidence.json").write_text(
            json.dumps([item.as_dict() for item in exc.evidence], sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        pytest.fail(str(exc))
    (artifact_root / "smoke-port-evidence.json").write_text(
        json.dumps([item.as_dict() for item in port_evidence], sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    summary.update(
        raw_save_reference=raw_reference,
        raw_save_sha256=manifest.live_summary.raw_save_sha256,
        parsed_artifact_reference=parsed_reference,
        parsed_artifact_sha256=manifest.live_summary.parsed_artifact_sha256,
        manifest_reference=f"run-{run_id}/outcome-v1.json",
        live_observed_kinds=sorted(live_kinds),
        live_observed_days=len(live_days),
        live_economy_values=len(live_cash),
        process_count=1,
        parser_count=1,
        cleanup_succeeded=True,
        save_events=save_events,
        task_count=len(tasks),
        task_cleanup_succeeded=True,
        signal_handlers_restored=True,
        game_port=game_port,
        admin_port=admin_port,
        ports_released=True,
        workspace_removed=True,
        lease_released=True,
    )
    fixture = Path(__file__).parent / "fixtures/openttd_13_4/seed-17-simpleai-road.sav"
    assert (
        hashlib.sha256(fixture.read_bytes()).hexdigest()
        == "062f7cb99d3fb4fb8ee722191c537331fd0f4e8e6f663b88ac3ab3b9d7ad7fad"
    )
    (artifact_root / "smoke-evidence.json").write_text(
        json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print("T17_SMOKE_PASS " + json.dumps(summary, sort_keys=True))
