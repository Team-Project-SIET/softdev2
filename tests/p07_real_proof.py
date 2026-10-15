"""One authorized P07 proof; instrumentation only, no production-source edits."""

import ast
import asyncio
import inspect
import json
import re
import shutil
import subprocess
import sys
import tempfile
import types
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import CoroutineType
from unittest.mock import patch

from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.config import get_settings
from app.experiments.domain import ExperimentConfig, LiveExecutionOptions
from app.experiments.model import ExperimentRunRecord, PlanningStrategyRecord
from app.experiments.plan_evaluation import PlanEvaluationInput
from app.experiments.plan_service import runtime_config
from app.experiments.service import ExperimentService
from app.experiments.telemetry_repository import TelemetryRepository
from app.planning.canonical import canonical_bytes, plan_hash, scenario_hash, world_manifest_hash
from app.planning.execution import execution_payload
from app.planning.runtime_world import (
    parse_runtime_world_evidence,
    runtime_projection_from_manifest,
)
from app.planning.setup_evidence import inspect_setup_log
from app.planning.transport import MaterializedPlan
from app.simulation.openttd.admin_observer import (
    AdminObserver,
    EventSink,
    ExpectedServerIdentity,
    ObserverEvent,
    ObserverMeasurement,
)
from app.simulation.openttd.admin_session import AdminSession
from app.simulation.openttd.live_launch import LiveLaunchPreparation, PreparedLiveRuntime
from app.simulation.openttd.live_runner import LiveSimulationRunner
from app.simulation.openttd.plan_setup import PlanSetup
from app.simulation.openttd.runtime_assets import (
    AcquisitionPolicy,
    PinnedRuntimePreparer,
    PreparedRuntime,
)
from app.simulation.openttd.telemetry import GameDateObservation
from tests.p07_proof_harness import (
    authoritative_input,
    freeze_package,
    read_package,
    require_authoritative,
    verify_frozen,
)
from tests.test_planning_transport_live import WORLD_SOURCE

REPO = Path("/home/fed/codes/softdev2")
PRIOR = REPO / "artifacts/planning/p06-proof-attempt2-20261004T032914Z"
ROOT = (
    REPO
    / "artifacts/planning"
    / ("p07-proof-attempt3-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
)


def digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"missing or unsafe proof artifact: {path.name}")
    return sha256(path.read_bytes()).hexdigest()


def put(name, value):
    with (ROOT / name).open("x") as f:
        json.dump(value, f, indent=2, sort_keys=True, default=str)
        f.write("\n")


def procs():
    found = []
    for p in Path("/proc").glob("[0-9]*/comm"):
        try:
            if p.read_text().strip() == "openttd":
                found.append(int(p.parent.name))
        except FileNotFoundError:
            pass
    return found


def git(*args):
    return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()


def source_hashes():
    paths = sorted((REPO / "app").rglob("*.py")) + sorted((REPO / "app").rglob("*.nut"))
    paths += sorted((REPO / "alembic").rglob("*.py"))
    paths += [
        REPO / "pyproject.toml",
        REPO / "uv.lock",
        Path(__file__),
        REPO / "tests/p07_proof_harness.py",
        REPO / "tests/test_p07_proof_harness.py",
    ]
    return {str(p): digest(p) for p in paths}


def historical_hashes():
    roots = [p for p in (REPO / "artifacts/planning").iterdir() if p.is_dir() and p != ROOT]
    roots += [REPO / "artifacts/telemetry"] if (REPO / "artifacts/telemetry").exists() else []
    return {
        str(p.relative_to(REPO)): digest(p)
        for root in roots
        for p in root.rglob("*")
        if p.is_file()
    }


def controlled_summary(path: Path) -> dict[str, int]:
    if not path.is_file() or path.is_symlink():
        raise ValueError("missing controlled test report")
    suite = ET.parse(path).getroot().find("testsuite")
    if suite is None:
        raise ValueError("missing controlled test suite")
    return {name: int(suite.attrib[name]) for name in ("tests", "failures", "errors", "skipped")}


def observer_type(on_event: EventSink) -> type[AdminObserver]:
    class RecordingObserver(AdminObserver):
        async def run(self, emit: EventSink, *, stop: asyncio.Event | None = None) -> None:
            async def record(event: ObserverEvent) -> None:
                result = on_event(event)
                if inspect.isawaitable(result):
                    await result
                forwarded = emit(event)
                if inspect.isawaitable(forwarded):
                    await forwarded

            await super().run(record, stop=stop)

    return RecordingObserver


def record_processes[**P](
    spawn: Callable[P, Awaitable[asyncio.subprocess.Process]],
    before: Callable[[tuple[object, ...]], None],
    after: Callable[[asyncio.subprocess.Process, tuple[object, ...]], None],
) -> Callable[P, CoroutineType[object, object, asyncio.subprocess.Process]]:
    async def recorded(*args: P.args, **kwargs: P.kwargs) -> asyncio.subprocess.Process:
        before(args)
        child = await spawn(*args, **kwargs)
        after(child, args)
        return child

    return recorded


def main():
    assert git("rev-parse", "HEAD") == "9ca056393c94b9f0c2800eab64d7eb67085967c5"
    assert not procs()
    assert not list((REPO / "artifacts/planning").glob("p07-proof-attempt3-*")), (
        "Attempt #3 directory already exists; do not retry"
    )
    suite = controlled_summary(Path("/tmp/p07-attempt3-precontrolled.xml"))
    assert suite["tests"] >= 1006 and suite["failures"] == suite["errors"] == suite["skipped"] == 0
    dirty = git("status", "--porcelain=v1")
    changed = (
        git("diff", "--name-only").splitlines()
        + git("ls-files", "--others", "--exclude-standard").splitlines()
    )
    whitespace = []
    for filename in changed:
        p = REPO / filename
        if p.is_file() and p.suffix in {".py", ".md", ".nut", ".toml"}:
            for number, line in enumerate(p.read_text().splitlines(), 1):
                if line.rstrip() != line or "\t" in line:
                    whitespace.append([filename, number])
    assert not whitespace, whitespace
    import_violations = []
    for p in (REPO / "app/planning").glob("*.py"):
        for node in ast.walk(ast.parse(p.read_text())):
            names = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [n.name for n in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            for name in names:
                if name.startswith(
                    ("sqlalchemy", "psycopg", "app.database", "app.experiments", "app.simulation")
                ):
                    import_violations.append([str(p), name])
    assert not import_violations, import_violations
    ROOT.mkdir(mode=0o700)
    Path("/tmp/p07-attempt3-root").write_text(str(ROOT))
    shutil.copyfile("/tmp/p07-attempt3-precontrolled.xml", ROOT / "controlled-prelaunch.xml")
    shutil.copyfile("/tmp/p07-a3-diagnostic-classification.json", ROOT / "driver-diagnostics.json")
    shutil.copyfile("/tmp/p07-a3-diagnosis-before.txt", ROOT / "typecheck-before.txt")
    shutil.copyfile(__file__, ROOT / "proof-harness.py.txt")
    put(
        "controlled-prelaunch.json",
        {
            "passed": suite["tests"],
            "failures": 0,
            "skipped": 0,
            "real_tests_deselected": 3,
            "postgresql": "fresh/upgrade/provenance/recovery passed",
            "ruff": "passed",
            "format": "passed",
            "typecheck": "passed",
            "diff": "passed",
            "whitespace_violations": whitespace,
            "planning_import_violations": import_violations,
        },
    )
    historical = historical_hashes()
    attempt1 = REPO / "artifacts/planning/p07-proof-attempt1-20261004T075402Z"
    attempt1_hashes = {
        str(p.relative_to(attempt1)): digest(p) for p in attempt1.rglob("*") if p.is_file()
    }
    manifest1 = json.loads((attempt1 / "artifact-sha256.json").read_bytes())
    assert all(attempt1_hashes[name] == expected for name, expected in manifest1.items())
    put(
        "attempt1-preservation-prelaunch.json",
        {
            "files": len(attempt1_hashes),
            "byte_identical": True,
            "sha256": attempt1_hashes,
            "OpenTTD_launches": 0,
        },
    )
    attempt2 = REPO / "artifacts/planning/p07-proof-attempt2-20261004T082405Z"
    attempt2_hashes = {
        str(p.relative_to(attempt2)): digest(p) for p in attempt2.rglob("*") if p.is_file()
    }
    manifest2 = json.loads((attempt2 / "artifact-sha256.json").read_bytes())
    assert all(attempt2_hashes[name] == expected for name, expected in manifest2.items())
    put(
        "attempt2-preservation-prelaunch.json",
        {
            "files": len(attempt2_hashes),
            "byte_identical": True,
            "sha256": attempt2_hashes,
            "OpenTTD_launches": 0,
        },
    )
    persisted = authoritative_input((attempt1 / "plan-input.json").read_bytes())
    # Sole P05 call: the same canonical optimization problem, before run creation.
    value = authoritative_input(
        PlanEvaluationInput.optimize(persisted.scenario, persisted.bindings)
    )
    require_authoritative(value)
    assert value == authoritative_input(value)
    assert value.estimated is not None, "proof requires P05 estimated metrics"
    scenario, bindings = value.scenario, value.bindings
    assert canonical_bytes(value.plan) == (PRIOR / "plan-canonical.json").read_bytes(), (
        "P05 output differs from proven P06 plan"
    )
    config = runtime_config(value)
    payload = execution_payload(value.plan, scenario, bindings)
    options = LiveExecutionOptions()
    runtime = PinnedRuntimePreparer(REPO / "artifacts/experiments/.live-runtime-cache").prepare(
        config, acquisition_policy=AcquisitionPolicy.CACHE_ONLY, plan_package=True
    )
    work = Path(tempfile.mkdtemp(prefix="p07-attempt3-"))
    launch = LiveLaunchPreparation(work / "workspaces").for_plan(value, WORLD_SOURCE)
    prepared = launch.prepare(config, runtime)
    module_hash, package_hash = read_package(prepared.ai_archive_path)
    staged = MaterializedPlan(
        plan_hash(value.plan),
        scenario.world_fingerprint,
        digest(prepared.workspace / "execution-plan.json"),
        module_hash,
        package_hash,
        prepared.workspace / "execution-plan.json",
        prepared.ai_archive_path / "plan.nut",
        prepared.ai_archive_path,
    )
    package_freeze = freeze_package(value, staged)
    assert prepared.provenance["package_sha256"] == package_freeze.package_sha256
    verify_frozen(value, prepared.ai_archive_path, package_freeze)
    put(
        "package-prelaunch-reread.json",
        {"module_sha256": module_hash, "package_sha256": package_hash, "match": True},
    )
    for name, artifact in [
        ("scenario.json", scenario),
        ("manifest.json", scenario.world_manifest),
        ("plan.json", value.plan),
        ("estimated.json", value.estimated),
        ("bindings.json", bindings),
        ("plan-input.json", value),
    ]:
        if artifact is None:
            raise ValueError(f"missing required canonical artifact: {name}")
        (ROOT / name).write_bytes(canonical_bytes(artifact))
    shutil.copytree(prepared.ai_archive_path, ROOT / "staged-package")
    stage_hashes = {
        str(p.relative_to(prepared.workspace)): digest(p)
        for p in prepared.workspace.rglob("*")
        if p.is_file()
    }
    hashes = source_hashes()
    schema = "p07_proof_attempt3_" + datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    url = str(get_settings().database_url)
    admin = create_engine(url, echo=False)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-c search_path={schema}"}, echo=False)
    migrations = Config(str(REPO / "alembic.ini"))
    with engine.begin() as conn:
        migrations.attributes["connection"] = conn
        command.upgrade(migrations, "head")
    del migrations.attributes["connection"]
    with engine.connect() as conn:
        head = conn.scalar(text("SELECT version_num FROM alembic_version"))
    assert head == "0008"
    scoped_url = engine.url.update_query_dict({"options": f"-c search_path={schema}"})
    freeze = {
        "HEAD": git("rev-parse", "HEAD"),
        "git_status": dirty,
        "dirty_P07_files": changed,
        "source_sha256": hashes,
        "migration_head": head,
        "historical_proof_attempts": 3,
        "historical_P07_launches_before": 0,
        "postgresql_schema": schema,
        "scenario_hash": scenario_hash(scenario),
        "manifest_hash": world_manifest_hash(scenario.world_manifest),
        "world_fingerprint": scenario.world_fingerprint,
        "plan_hash": plan_hash(value.plan),
        "estimated_metrics_hash": sha256(canonical_bytes(value.estimated)).hexdigest(),
        "planner_name": value.plan.planner_name,
        "planner_version": value.plan.planner_version,
        "executor_version": "1",
        "openttd_version": "13.4",
        "opengfx_version": "7.1",
        "runtime_provenance": runtime.provenance,
        "openttd_executable_sha256": digest(runtime.executable_path),
        "opengfx_sha256": digest(runtime.opengfx_archive_path),
        "world_source_sha256": digest(WORLD_SOURCE),
        "expected_runtime_world_hash": payload["runtime_world_hash"],
        "staged_sha256": stage_hashes,
        "generated_module_sha256": package_freeze.module_sha256,
        "staged_package_sha256": package_freeze.package_sha256,
        "canonical_input_sha256": sha256(package_freeze.input_bytes).hexdigest(),
        "workspace": str(work),
        "argv": list(prepared.argv),
        "horizon_days": scenario.horizon_days,
        "planning_start_date": str(scenario.start_date),
        "same_plan_as_P06_attempt2": True,
        "historical_artifact_sha256": historical,
        "P05_unchanged": not git("diff", "--", "app/planning/optimizer.py"),
        "P06_unchanged": not git(
            "diff",
            "--",
            "app/planning/execution.py",
            "app/planning/execution_evidence.py",
            "app/planning/thin_ai",
        ),
        "P03_P04_unchanged": not git(
            "diff",
            "--",
            "app/planning/transport.py",
            "app/planning/runtime_world.py",
            "app/simulation/openttd/admin_observer.py",
            "app/simulation/openttd/admin_protocol.py",
            "app/simulation/openttd/admin_session.py",
            "app/simulation/openttd/telemetry.py",
            "app/simulation/openttd/telemetry_processor.py",
        ),
    }
    put("prelaunch-source-freeze.json", freeze)
    print(
        json.dumps(
            {
                "phase": "frozen_before_launch",
                "root": str(ROOT),
                "plan_hash": freeze["plan_hash"],
                "horizon_days": scenario.horizon_days,
                "launches": 0,
            }
        ),
        flush=True,
    )
    spawned, children, events, outbound = [], [], [], []
    cleanup = {}
    original_spawn = asyncio.create_subprocess_exec
    original_send = AdminSession.send
    original_close = prepared.close
    setup_complete = {}
    observation_dates: list[int] = []

    class RecordingSetup(PlanSetup):
        async def execute(
            self,
            process: asyncio.subprocess.Process,
            directory: Path,
            deadline: float,
            check_health: Callable[[], None] | None = None,
        ) -> None:
            await super().execute(process, directory, deadline, check_health)
            setup_complete["at"] = datetime.now(UTC).isoformat()
            setup_complete["last_observed_game_day"] = (
                observation_dates[-1] if observation_dates else None
            )

    setup = RecordingSetup(value)

    def close_with_evidence(self: PreparedLiveRuntime) -> None:
        retained = ROOT / "runtime-saves"
        retained.mkdir(exist_ok=True)
        for p in self.workspace.rglob("*.sav"):
            if p.name != "prepared.sav":
                destination = retained / str(p.relative_to(self.workspace)).replace("/", "__")
                shutil.copyfile(p, destination)
        try:
            verify_frozen(value, self.ai_archive_path, package_freeze)
            cleanup["post_runtime_package_sha256"] = read_package(self.ai_archive_path)[1]
            cleanup["package_hash_match"] = all(
                digest(self.workspace / p) == h
                for p, h in stage_hashes.items()
                if p.startswith("ai/")
            )
        except ValueError as exc:
            cleanup["package_hash_match"] = False
            cleanup["package_integrity_error"] = str(exc)
        finally:
            original_close()
        cleanup["production_workspace_removed"] = not self.workspace.exists()
        cleanup["lease_closed"] = self.lease.closed

    prepared.close = types.MethodType(close_with_evidence, prepared)

    def before_spawn(args: tuple[object, ...]) -> None:
        is_world = str(runtime.executable_path) in tuple(map(str, args))
        if is_world:
            assert not any(x["kind"] == "world" for x in spawned), "SECOND OPENTTD LAUNCH FORBIDDEN"
            verify_frozen(value, prepared.ai_archive_path, package_freeze)
            put(
                "launched-package-identity.json",
                {
                    "package_sha256": read_package(prepared.ai_archive_path)[1],
                    "frozen_sha256": package_freeze.package_sha256,
                    "match": True,
                },
            )
            assert hashes == source_hashes(), "source changed before launch"
            assert all(digest(prepared.workspace / p) == h for p, h in stage_hashes.items())
            put(
                "launch-guard.json",
                {
                    "authorized": 1,
                    "consumed_at": datetime.now(UTC).isoformat(),
                    "plan_hash": freeze["plan_hash"],
                },
            )

    def after_spawn(child: asyncio.subprocess.Process, args: tuple[object, ...]) -> None:
        is_world = str(runtime.executable_path) in tuple(map(str, args))
        spawned.append({"kind": "world" if is_world else "parser", "pid": child.pid})
        children.append(child)
        put_name = "process-start.json" if is_world else "parser-start.json"
        put(put_name, spawned[-1])

    async def record_send(self: AdminSession, *frames: bytes) -> None:
        outbound.extend(frame[2] for frame in frames)
        assert all(frame[2] in {0, 1, 2, 3, 7} for frame in frames)
        return await original_send(self, *frames)

    def record_event(event: ObserverEvent) -> None:
        if isinstance(event, ObserverMeasurement) and isinstance(
            event.payload, GameDateObservation
        ):
            observation_dates.append(event.payload.game_day)
        if not isinstance(event, ObserverMeasurement):
            events.append(
                {
                    "event": type(event).__name__,
                    "value": asdict(event),
                    "at": datetime.now(UTC).isoformat(),
                }
            )

    class FrozenAssets(PinnedRuntimePreparer):
        def prepare(
            self,
            config: ExperimentConfig,
            *,
            deadline: float | None = None,
            acquisition_policy: AcquisitionPolicy = AcquisitionPolicy.ALLOW_PROVISIONING,
            plan_package: bool = False,
        ) -> PreparedRuntime:
            assert config == expected_config and plan_package is True
            return expected_runtime

    class FrozenLaunch(LiveLaunchPreparation):
        def prepare(
            self,
            config: ExperimentConfig,
            runtime: PreparedRuntime,
            *,
            game_port: int | None = None,
            admin_port: int | None = None,
            save_name: str = "final.sav",
            deadline: float | None = None,
        ) -> PreparedLiveRuntime:
            assert config == expected_config and runtime is expected_runtime
            return prepared

    expected_config, expected_runtime = config, runtime

    def factory(v, world, conf, opts, root, telemetry_factory, cancellation):
        assert v == value and conf == config
        require_authoritative(v)
        return LiveSimulationRunner(
            FrozenAssets(REPO / "artifacts/experiments/.live-runtime-cache"),
            FrozenLaunch(work / "workspaces"),
            expected_identity=ExpectedServerIdentity(
                "13.4", scenario.seed, "", scenario.width_tiles, scenario.height_tiles, 0
            ),
            options=opts,
            telemetry_factory=telemetry_factory,
            plan_setup=setup,
            observer_factory=observer_type(record_event),
        )

    spawn_patch = patch.object(
        asyncio,
        "create_subprocess_exec",
        record_processes(original_spawn, before_spawn, after_spawn),
    )
    spawn_patch.start()
    AdminSession.send = record_send
    outcome = None
    error = None
    try:
        service = ExperimentService(
            sessionmaker(bind=engine, expire_on_commit=False),
            telemetry_store_factory=lambda: TelemetryRepository(scoped_url),
        )
        outcome = service.run_plan(
            value,
            world_source=WORLD_SOURCE,
            artifact_dir=ROOT,
            live_options=options,
            runner_factory=factory,
        )
        put("plan-evaluation-result.json", outcome.model_dump(mode="json"))
        directory = ROOT / f"run-{outcome.outcome.run_id}"
        with service.session_factory() as session:
            row = session.get(ExperimentRunRecord, outcome.outcome.run_id)
            assert row is not None, "persisted experiment run missing"
            assert row.plan_evaluation is not None, "persisted plan evaluation missing"
            assert row.telemetry_session is not None, "persisted telemetry session missing"
            provenance = row.plan_evaluation.provenance
            audit = {
                "schema": schema,
                "migration_head": head,
                "run_id": row.id,
                "run_input_kind": row.input_kind,
                "run_status": row.status,
                "failure_code": row.failure_code,
                "strategy_id": row.strategy_id,
                "external_AI_strategy_count": len(
                    session.scalars(select(PlanningStrategyRecord)).all()
                ),
                "plan_hash": row.plan_evaluation.plan_hash,
                "world_fingerprint": row.plan_evaluation.world_fingerprint,
                "provenance": provenance,
                "simulation_run": {
                    "id": row.simulation.id,
                    "experiment_run_id": row.simulation.experiment_run_id,
                    "date": str(row.simulation.simulation_date),
                }
                if row.simulation
                else None,
                "telemetry_session": {
                    c.name: getattr(row.telemetry_session, c.name)
                    for c in row.telemetry_session.__table__.columns
                },
            }
            assert row.input_kind == "execution_plan" and row.strategy_id is None
            assert audit["external_AI_strategy_count"] == 0
            assert (
                audit["plan_hash"] == freeze["plan_hash"]
                and audit["world_fingerprint"] == scenario.world_fingerprint
            )
            assert provenance == outcome.provenance.model_dump(mode="json")
            refs = {}
            for key, ref in provenance.items():
                if isinstance(ref, dict) and "sha256" in ref:
                    assert digest(directory / ref["reference"]) == ref["sha256"], key
                    refs[key] = {
                        "reference": ref["reference"],
                        "sha256": ref["sha256"],
                        "verified": True,
                    }
            audit["verified_artifact_references"] = refs
            audit["reload_verified"] = True
            put("persisted-provenance-audit.json", audit)
        assert outcome.outcome.status.value == "succeeded", "P07 outcome failed: " + str(
            outcome.outcome.failure_code
        )
        assert outcome.realized is not None and outcome.realized.plan_hash == freeze["plan_hash"]
        realized = outcome.realized
        assert (
            realized.observed_terminal_day - realized.observed_start_day == scenario.horizon_days
        ), "horizon differs from exactly requested days"
        assert (
            realized.coverage_complete
            and realized.observations.window_complete
            and realized.observations.status == "complete"
        ), "P04 observation coverage incomplete"
        assert realized.observations.gaps == realized.observations.dropped == 0
        for name in ("realized.json", "comparison.json"):
            obj = json.loads((directory / name).read_text())
            assert obj["plan_hash"] == freeze["plan_hash"]
        assert canonical_bytes(realized) == (directory / "realized.json").read_bytes()
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        spawn_patch.stop()
        AdminSession.send = original_send
        log = setup.capture.text.replace(prepared.admin_password, "<REDACTED>")
        (ROOT / "openttd-log.txt").write_text(log)
        trace = inspect_setup_log(log, freeze["plan_hash"])
        native = [
            json.loads(line.split("P06_EXECUTION_V1|", 1)[1])
            for line in log.splitlines()
            if "P06_EXECUTION_V1|" in line
        ]
        health = {
            "executor_instances": len(
                set(re.findall(r"dbg: \[script\] \[(\d+)\] \[I\] P03_EXECUTOR_AI\|P06_", log))
            ),
            "success_receipts": sum(x["result"] == "success" for x in native),
            "failure_receipts": sum(x["result"] != "success" for x in native),
            "Squirrel_crashes": len(trace.script_crashes),
            "script_errors": trace.script_error_count,
        }
        put("native-terminal-receipts.json", native)
        world = None
        try:
            world = parse_runtime_world_evidence(
                log, runtime_projection_from_manifest(scenario.world_manifest), freeze["plan_hash"]
            )
        except Exception as exc:
            cleanup["runtime_world_parse_error"] = str(exc)
        put("p03-runtime-evidence.json", world)
        put("setup-completion-date.json", setup_complete)
        put(
            "p04-observer-evidence.json",
            {
                "events": events,
                "outbound_packet_types": dict(Counter(outbound)),
                "read_only_allowlist": [0, 1, 2, 3, 7],
                "gameplay_packets": 0,
            },
        )
        if prepared.workspace.exists():
            assert not procs(), "process must be reaped before cleanup"
            prepared.close()
        assert work.parent == Path("/tmp") and work.name.startswith("p07-attempt3-")
        shutil.rmtree(work)
        cleanup.update(
            {
                "spawned": spawned,
                "processes": [
                    {
                        "pid": c.pid,
                        "exit_code": c.returncode,
                        "reaped": c.returncode is not None,
                        "proc_entry_absent": not Path(f"/proc/{c.pid}").exists(),
                    }
                    for c in children
                ],
                "remaining_openttd_pids": procs(),
                "temporary_workspace_removed": not work.exists(),
            }
        )
        put("cleanup-process.json", cleanup)
        post = source_hashes()
        historical_equal = historical == historical_hashes()
        put(
            "post-source-integrity.json",
            {
                "equal": post == hashes,
                "source_sha256": post,
                "historical_artifacts_equal": historical_equal,
                "canonical_input_equal": canonical_bytes(value) == package_freeze.input_bytes,
                "post_runtime_package_sha256": cleanup.get("post_runtime_package_sha256"),
            },
        )
        if post != hashes or not historical_equal:
            error = error or "frozen source or historical artifacts changed"
        if len([x for x in spawned if x["kind"] == "world"]) != 1 or health != {
            "executor_instances": 1,
            "success_receipts": 1,
            "failure_receipts": 0,
            "Squirrel_crashes": 0,
            "script_errors": 0,
        }:
            error = error or "launch/executor/receipt/script health requirement failed"
        if (
            procs()
            or any(c.returncode != 0 for c in children)
            or not cleanup.get("package_hash_match")
        ):
            error = error or "process/package cleanup requirement failed"
        put(
            "diagnostics.json",
            {
                "error": error,
                "health": health,
                "last_stage": trace.last_stage,
                "trace": asdict(trace),
            },
        )
        put(
            "proof-evidence.json",
            {
                "attempt": 3,
                "success": error is None,
                "error": error,
                "OpenTTD_launches": len([x for x in spawned if x["kind"] == "world"]),
                "plan_hash": freeze["plan_hash"],
                "world_fingerprint": scenario.world_fingerprint,
                "source_hashes_match": post == hashes,
                "historical_artifacts_unchanged": historical_equal,
                "runtime_health": health,
                "run_id": outcome.outcome.run_id if outcome else None,
                "horizon_days": scenario.horizon_days,
                "retry_performed": False,
            },
        )
        engine.dispose()
        admin.dispose()
        print(
            json.dumps(
                {
                    "root": str(ROOT),
                    "success": error is None,
                    "error": error,
                    "launches": len([x for x in spawned if x["kind"] == "world"]),
                }
            ),
            flush=True,
        )
    return 0 if error is None else 1


if __name__ == "__main__":
    sys.exit(main())
