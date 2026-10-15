"""Single opt-in P03 transport proof; no construction, DB or Admin control."""

import hashlib
import json
import os
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import TypedDict

import pytest
from openttdlab import parse_savegame

from app.experiments.domain import ExperimentConfig, ScenarioConfig
from app.experiments.strategies import SimpleRoadOnlyStrategy
from app.planning.domain import ExecutionPlan, PlanningScenario, Tile, WorldReference
from app.planning.runtime_world import (
    parse_runtime_world_evidence,
    runtime_projection_from_manifest,
    runtime_world_hash,
)
from app.planning.serialization import plan_artifact_bytes, plan_hash, world_manifest_hash
from app.planning.setup_evidence import (
    UNPAUSE_ACK,
    SetupEvidenceError,
    SetupLogCapture,
    parse_setup_evidence,
)
from app.planning.transport import (
    MaterializedPlan,
    materialize_plan,
    transport_bytes,
    verify_staged_package,
)
from app.planning.validation import validate_execution_plan
from app.simulation.openttd.runtime_assets import AcquisitionPolicy, PinnedRuntimePreparer
from tests.test_planning import tiny_plan, tiny_scenario

WORLD_SOURCE = Path(__file__).parent / "fixtures/openttd_13_4/seed-17-simpleai-road.sav"
HANDSHAKE_READY = "__P03_HANDSHAKE_READY__"
COMPANIES_DONE = "__P03_COMPANIES_DONE__"
STOP_DONE = "__P03_STOP_DONE__"
START_DONE = "__P03_START_DONE__"
COMPANIES_COMMAND = "dbg: [console] Executing cmdline: 'companies'"
START_COMMAND = "dbg: [console] Executing cmdline: 'start_ai P03ThinExecutor'"
MAX_COMPANY_POLLS = 20
COMPANY_POLL_INTERVAL_SECONDS = 0.2
ATTEMPT2_ROOT = Path(__file__).parents[1] / "artifacts/planning/p03-proof-attempt2-20260928"
ATTEMPT2_FILE_COUNT = 159
ATTEMPT2_DIGEST = "dfc3395922a5d569ae14bb215f4263b00b7e32d4276e6222037d099293d5379f"
_COMPANY_ROW = re.compile(
    r"^#:(?P<id>[1-9]|1[0-5])\([^)]*\) Company Name: '.*'  Year Founded: .*  "
    r"\(T:\d+, R:\d+, P:\d+, S:\d+\) (?P<owner>AI|unprotected|protected)?$"
)


_FAKE_CONSOLE_INPUT = """
import sys
_original_input = sys.stdin
class ConsoleInput:
    def readline(self):
        while True:
            line = _original_input.readline()
            if not line: return line
            command = line.strip()
            print("dbg: [console] Executing cmdline: '" + command + "'", flush=True)
            if command.startswith('echo '):
                print(command[5:], flush=True)
                continue
            return line
sys.stdin = ConsoleInput()
print('__P03_HANDSHAKE_READY__', flush=True)
"""


@dataclass(frozen=True)
class _ConsoleLine:
    command: str
    required_output: tuple[str, ...]


class _ProofPopenOptions(TypedDict):
    cwd: Path
    stdin: int
    stdout: int
    stderr: int
    bufsize: int


def _fake_company_row(company_id: int, colour: str, name: str) -> str:
    return (
        f"#:{company_id}({colour}) Company Name: '{name}'  Year Founded: 1950  "
        "Money: 100  Loan: 0  Value: 100  (T:0, R:0, P:0, S:0) AI"
    )


def _artifact_tree_digest(root: Path) -> tuple[int, str]:
    if not root.is_dir() or root.is_symlink():
        raise SetupEvidenceError("attempt #2 artifact root is unavailable")
    paths = sorted(root.rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise SetupEvidenceError("attempt #2 artifact tree contains a symlink")
    files = [path for path in paths if path.is_file()]
    digest = hashlib.sha256()
    for path in files:
        digest.update(str(path.relative_to(root)).encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return len(files), digest.hexdigest()


def _verify_attempt2_artifacts(
    root: Path, *, expected_count: int | None = None, expected_digest: str | None = None
) -> tuple[int, str]:
    if expected_count is None:
        expected_count = ATTEMPT2_FILE_COUNT
    if expected_digest is None:
        expected_digest = ATTEMPT2_DIGEST
    count, digest = _artifact_tree_digest(root)
    if count != expected_count or digest != expected_digest:
        raise SetupEvidenceError("attempt #2 artifact digest mismatch")
    return count, digest


@pytest.fixture(autouse=True)
def controlled_proof_inputs(request, tmp_path, monkeypatch):
    """Ordinary tests own their prior proof and cannot fetch official assets.

    The opt-in real test retains the immutable historical root and digest.
    """
    if request.node.get_closest_marker("openttd") is not None:
        return
    from app.simulation.openttd.runtime_assets import OfficialRuntimeSource

    prior = tmp_path / "prior-proof"
    prior.mkdir()
    (prior / "receipt.json").write_text('{"status":"historical-fixture"}\n')
    count, digest = _artifact_tree_digest(prior)
    module = sys.modules[__name__]
    monkeypatch.setattr(module, "ATTEMPT2_ROOT", prior)
    monkeypatch.setattr(module, "ATTEMPT2_FILE_COUNT", count)
    monkeypatch.setattr(module, "ATTEMPT2_DIGEST", digest)

    def forbidden_fetch(*args, **kwargs):
        raise AssertionError("ordinary P03 tests must not download runtime assets")

    monkeypatch.setattr(OfficialRuntimeSource, "fetch", forbidden_fetch)


def _prepare_controlled_runtime_cache(cache: Path, monkeypatch):
    """Exercise the real preparer using deterministic local archives and pins."""
    from tests.test_runtime_assets import _config, _fixture_assets, _LocalSource

    pins, blobs = _fixture_assets()
    preparer_type = PinnedRuntimePreparer

    def local_preparer(cache_root):
        return preparer_type(cache_root, source=_LocalSource(blobs), pins=pins)

    monkeypatch.setattr(sys.modules[__name__], "PinnedRuntimePreparer", local_preparer)
    return local_preparer(cache).prepare(_config(SimpleRoadOnlyStrategy()))


def _persist_prelaunch_record(root: Path, record: dict[str, object]) -> None:
    """Expose a complete JSON record atomically, without replacing an old proof."""
    target = root / "p03-proof-prelaunch.json"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=root, prefix=".p03-prelaunch-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(record, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, target, follow_symlinks=False)
        target.chmod(0o400)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    if json.loads(target.read_text(encoding="utf-8")) != record:
        raise SetupEvidenceError("persisted P03 prelaunch record differs")


def pinned_plan_and_scenario(source: Path) -> tuple[ExecutionPlan, PlanningScenario]:
    assert source.is_file() and not source.is_symlink()
    with source.open("rb") as stream:
        saved = parse_savegame(iter(lambda: stream.read(65536), b""))
    assert saved["chunks"]["MAPS"]["records"]["0"] == {"dim_x": 256, "dim_y": 256}
    assert saved["chunks"]["PATS"]["records"]["0"]["game_creation.generation_seed"] == 17
    assert saved["chunks"]["DATE"]["records"]["0"]["pause_mode"] == 1
    industries = saved["chunks"]["INDY"]["records"]
    assert industries["0"]["location.tile"] == 70 * 256 + 168
    assert industries["1"]["location.tile"] == 214 * 256 + 203
    assert industries["0"]["produced_cargo"][0] == 1
    assert industries["1"]["accepts_cargo"][0] == 1
    # P03 resolves these industry IDs. It does not build the corridor.
    scenario = tiny_scenario()
    sites = list(scenario.world_manifest.resolved_sites)
    sites[0] = sites[0].model_copy(
        update={"tile": Tile(x=168, y=70), "world_kind": "industry", "world_id": 0}
    )
    sites[1] = sites[1].model_copy(
        update={"tile": Tile(x=203, y=214), "world_kind": "industry", "world_id": 1}
    )
    manifest = scenario.world_manifest.model_copy(
        update={
            "source_digest": hashlib.sha256(source.read_bytes()).hexdigest(),
            "width_tiles": 256,
            "height_tiles": 256,
            "resolved_sites": tuple(sites),
        }
    )
    fingerprint = world_manifest_hash(manifest)
    locations = list(scenario.locations)
    locations[0] = locations[0].model_copy(
        update={
            "tile": Tile(x=168, y=70),
            "world_reference": WorldReference(
                world_fingerprint=fingerprint, kind="industry", world_id=0
            ),
        }
    )
    locations[1] = locations[1].model_copy(
        update={
            "tile": Tile(x=203, y=214),
            "world_reference": WorldReference(
                world_fingerprint=fingerprint, kind="industry", world_id=1
            ),
        }
    )
    scenario = scenario.model_copy(
        update={
            "world_manifest": manifest,
            "world_fingerprint": fingerprint,
            "width_tiles": 256,
            "height_tiles": 256,
            "locations": tuple(locations),
        }
    )
    plan = tiny_plan()
    declaration = plan.validation.model_copy(update={"validated_world_fingerprint": fingerprint})
    plan = plan.model_copy(update={"world_fingerprint": fingerprint, "validation": declaration})

    return plan, scenario


def prepare_proof_workspace(
    workspace: Path, plan: ExecutionPlan, scenario: PlanningScenario, source: Path, graphics: Path
) -> tuple[MaterializedPlan, Path, Path]:
    receipt = materialize_plan(plan, scenario, plan_hash(plan), workspace, source)
    verify_staged_package(receipt)
    (workspace / "baseset").mkdir(mode=0o700)
    shutil.copyfile(graphics, workspace / "baseset" / "opengfx-7.1.tar")
    (workspace / "save").mkdir(mode=0o700)
    save = workspace / "save" / "world.sav"
    shutil.copyfile(source, save)
    assert hashlib.sha256(save.read_bytes()).hexdigest() == scenario.world_manifest.source_digest
    save.chmod(0o600)
    (workspace / "scripts").mkdir(mode=0o700)
    (workspace / "scripts" / "game_start.scr").write_text(
        f"echo {HANDSHAKE_READY}\n", encoding="ascii"
    )
    (workspace / "scripts" / "p03_unpause.scr").write_text(
        f"unpause\necho {UNPAUSE_ACK}\n", encoding="ascii"
    )
    config_path = workspace / "openttd.cfg"
    config_path.write_text(
        "[version]\nversion_string = 13.4\nini_version = 2\n"
        "[game_creation]\nmap_x = 8\nmap_y = 8\nstarting_year = 1950\n"
        "[network]\nserver_game_type = local\nmin_active_clients = 0\n"
        "restart_game_year = 0\nreload_cfg = false\n"
        "[ai]\nai_in_multiplayer = true\n"
        "[ai_players]\nP03ThinExecutor =\n",
        encoding="ascii",
    )
    for path in (
        workspace / "baseset" / "opengfx-7.1.tar",
        workspace / "scripts" / "game_start.scr",
        workspace / "scripts" / "p03_unpause.scr",
        config_path,
    ):
        path.chmod(0o600)
    return receipt, config_path, save


def _company_listing(lines: list[str], marker: str) -> dict[int, bool]:
    """Read one complete 13.4 `companies` response bounded by a console echo."""
    if lines.count(marker) != 1:
        raise SetupEvidenceError(f"missing or repeated {marker} company-list marker")
    end = lines.index(marker)
    begin_marker = marker + "_BEGIN"
    if lines.count(begin_marker) != 1 or lines.index(begin_marker) >= end:
        raise SetupEvidenceError("missing or mismatched company-list BEGIN marker")
    begin = lines.index(begin_marker)
    starts = [index for index in range(begin + 1, end) if lines[index] == COMPANIES_COMMAND]
    if len(starts) != 1:
        raise SetupEvidenceError("company-list command was not observed exactly once")
    rows: dict[int, bool] = {}
    for line in lines[starts[-1] + 1 : end]:
        if not line.startswith("#:"):
            continue
        match = _COMPANY_ROW.fullmatch(line)
        if match is None:
            raise SetupEvidenceError(f"malformed company listing: {line[:160]}")
        company_id = int(match.group("id"))
        if company_id in rows:
            raise SetupEvidenceError("duplicate company identifier in listing")
        rows[company_id] = match.group("owner") == "AI"
    return rows


@pytest.mark.parametrize(
    "lines,error",
    [
        ([COMPANIES_COMMAND, "QUERY_END"], "BEGIN"),
        (["QUERY_END_BEGIN", COMPANIES_COMMAND], "QUERY_END"),
        (["OTHER_BEGIN", COMPANIES_COMMAND, "QUERY_END"], "BEGIN"),
        (["QUERY_END_BEGIN", COMPANIES_COMMAND, "OTHER"], "QUERY_END"),
    ],
)
def test_company_snapshot_requires_matching_boundaries(lines: list[str], error: str) -> None:
    with pytest.raises(SetupEvidenceError, match=error):
        _company_listing(lines, "QUERY_END")


def test_company_snapshot_accepts_completed_empty_listing() -> None:
    assert _company_listing(["QUERY_END_BEGIN", COMPANIES_COMMAND, "QUERY_END"], "QUERY_END") == {}


def observe_setup_child(
    child: subprocess.Popen[bytes], capture: SetupLogCapture, timeout_seconds: float
) -> bool:
    """Drive the P03-only paused-world transition from complete child log lines."""
    assert child.stdout is not None
    assert child.stdin is not None
    phase = "ready"
    old_company: int | None = None
    poll_marker = ""
    poll_count = 0
    next_poll_at = 0.0
    commands: list[_ConsoleLine] = []
    pending: _ConsoleLine | None = None
    sent_after = 0

    def execution(command: str) -> str:
        return f"dbg: [console] Executing cmdline: '{command}'"

    def enqueue(command: str, *required_output: str) -> None:
        commands.append(_ConsoleLine(command, (execution(command), *required_output)))

    def enqueue_query(marker: str) -> None:
        """Frame one snapshot and pace every line through its own observation."""
        enqueue(f"echo {marker}_BEGIN", f"{marker}_BEGIN")
        enqueue("companies")
        enqueue(f"echo {marker}", marker)

    def marker(base: str, count: int) -> str:
        return f"{base}_{count:02d}"

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if phase in ("stop_wait", "start_wait") and time.monotonic() >= next_poll_at:
            poll_count += 1
            base = STOP_DONE if phase == "stop_wait" else START_DONE
            poll_marker = marker(base, poll_count)
            enqueue_query(poll_marker)
            phase = "stop" if phase == "stop_wait" else "start"
        # 13.4 selects the fd before buffered fgets: never batch stdin lines.
        if pending is None and commands:
            pending = commands.pop(0)
            sent_after = len(capture.text.splitlines())
            child.stdin.write((pending.command + "\n").encode("ascii"))
            child.stdin.flush()
        ready, _, _ = select.select([child.stdout], [], [], 0.1)
        if not ready:
            if child.poll() is not None:
                break
            continue
        chunk = os.read(child.stdout.fileno(), 65536)
        if not chunk:
            break
        capture.feed(chunk)
        trace = capture.trace
        lines = capture.text.splitlines()
        completed_command: str | None = None
        recent = lines[sent_after:]
        if pending is not None and all(item in recent for item in pending.required_output):
            completed_command = pending.command
            pending = None
        if (
            pending is not None
            and pending.command.startswith("stop_ai ")
            and any(
                message in recent
                for message in (
                    "Unknown company. Company range is between 1 and 15.",
                    "Company is not controlled by an AI.",
                    "Only the server can stop an AI.",
                )
            )
        ):
            raise SetupEvidenceError(f"{pending.command} was not acknowledged")
        if trace.script_error_count:
            raise SetupEvidenceError(f"script error during P03 {phase} phase")
        if phase == "ready" and HANDSHAKE_READY in lines:
            enqueue_query(COMPANIES_DONE)
            phase = "discover"
        elif phase == "discover" and COMPANIES_DONE in lines:
            companies = _company_listing(lines, COMPANIES_DONE)
            candidates = [number for number, is_ai in companies.items() if is_ai]
            if len(candidates) != 1:
                raise SetupEvidenceError(f"expected one old AI company, found {len(candidates)}")
            old_company = candidates[0]
            stop_command = f"stop_ai {old_company}"
            enqueue(stop_command, "AI stopped, company deleted.")
            poll_count = 1
            poll_marker = marker(STOP_DONE, poll_count)
            phase = "stop_command"
        elif phase == "stop_command" and completed_command == f"stop_ai {old_company}":
            enqueue_query(poll_marker)
            phase = "stop"
        elif phase == "stop" and poll_marker in lines:
            assert old_company is not None
            companies = _company_listing(lines, poll_marker)
            if any(is_ai for number, is_ai in companies.items() if number != old_company):
                raise SetupEvidenceError("old AI remains after stop_ai")
            if old_company in companies:
                if poll_count >= MAX_COMPANY_POLLS:
                    raise SetupEvidenceError("old AI deletion was not observed")
                next_poll_at = time.monotonic() + COMPANY_POLL_INTERVAL_SECONDS
                phase = "stop_wait"
            else:
                enqueue("start_ai P03ThinExecutor")
                poll_count = 1
                poll_marker = marker(START_DONE, poll_count)
                phase = "start_command"
        elif phase == "start_command" and completed_command == "start_ai P03ThinExecutor":
            enqueue_query(poll_marker)
            phase = "start"
        elif phase == "start" and poll_marker in lines:
            companies = _company_listing(lines, poll_marker)
            ai_count = sum(companies.values())
            if ai_count > 1:
                raise SetupEvidenceError("more than one AI exists after P03ThinExecutor start")
            if ai_count == 0:
                if poll_count >= MAX_COMPANY_POLLS:
                    raise SetupEvidenceError("P03ThinExecutor company creation was not observed")
                next_poll_at = time.monotonic() + COMPANY_POLL_INTERVAL_SECONDS
                phase = "start_wait"
            else:
                enqueue("exec scripts/p03_unpause.scr", UNPAUSE_ACK)
                phase = "unpause_command"
        elif phase == "unpause_command" and completed_command == "exec scripts/p03_unpause.scr":
            phase = "unpause"
        if trace.terminal_count > 0:
            if phase != "unpause" or not trace.unpause_acknowledged:
                raise SetupEvidenceError("terminal evidence arrived before unpause")
            break
    if phase != "unpause":
        raise SetupEvidenceError(
            f"P03 handshake incomplete in {phase} phase; "
            f"pending command: {pending.command if pending else None}; "
            f"awaiting snapshot: {poll_marker or COMPANIES_DONE}"
        )
    return True


def test_controlled_p03_workspace_placement(tmp_path: Path) -> None:
    plan, scenario = pinned_plan_and_scenario(WORLD_SOURCE)
    validate_execution_plan(plan, scenario)
    graphics = tmp_path / "opengfx-7.1.tar"
    graphics.write_bytes(b"controlled graphics archive")
    workspace = tmp_path / "owned"
    workspace.mkdir(mode=0o700)
    receipt, config_path, save = prepare_proof_workspace(
        workspace, plan, scenario, WORLD_SOURCE, graphics
    )
    assert receipt.ai_directory == workspace / "ai" / "P03ThinExecutor"
    assert receipt.module_path == receipt.ai_directory / "plan.nut"
    assert (receipt.ai_directory / "info.nut").is_file()
    assert (receipt.ai_directory / "main.nut").is_file()
    assert b'require("plan.nut")' in (receipt.ai_directory / "main.nut").read_bytes()
    assert receipt.module_path.read_bytes() == transport_bytes(plan, scenario, plan_hash(plan))
    assert receipt.artifact_path.read_bytes() == plan_artifact_bytes(plan)
    assert save.read_bytes() == WORLD_SOURCE.read_bytes()
    assert config_path.is_file()
    assert (workspace / "scripts" / "game_start.scr").read_text() == (f"echo {HANDSHAKE_READY}\n")
    assert (workspace / "scripts" / "p03_unpause.scr").read_text() == (
        f"unpause\necho {UNPAUSE_ACK}\n"
    )
    assert str(WORLD_SOURCE).encode() not in receipt.module_path.read_bytes()
    assert b"password" not in receipt.module_path.read_bytes().lower()
    assert not any(path.is_symlink() for path in workspace.rglob("*"))
    verify_staged_package(receipt)


@pytest.mark.parametrize(
    "status,code", [("accepted", "NONE"), ("failed", "WORLD_RESOLUTION_FAILURE")]
)
def test_controlled_p03_lifecycle(tmp_path: Path, status: str, code: str) -> None:
    plan, scenario = pinned_plan_and_scenario(WORLD_SOURCE)
    graphics = tmp_path / "opengfx-7.1.tar"
    graphics.write_bytes(b"controlled graphics archive")
    with tempfile.TemporaryDirectory(dir=tmp_path, prefix="run-") as name:
        workspace = Path(name)
        workspace.chmod(0o700)
        prepare_proof_workspace(workspace, plan, scenario, WORLD_SOURCE, graphics)
        capture = SetupLogCapture(plan_hash(plan))
        capture.feed(b"dbg: [net] Starting dedicated server, version 13.4\n")
        assert capture.trace.last_stage == "PROCESS_STARTED"
        capture.feed(b"dbg: [console] Executing cmdline: 'stop_ai 3'\n")
        capture.feed(b"AI stopped, company deleted.\n")
        capture.feed(b"dbg: [console] Executing cmdline: 'start_ai P03ThinExecutor'\n")
        assert capture.trace.old_ai_stopped
        assert capture.trace.ai_selected
        capture.feed(f"{UNPAUSE_ACK}\n".encode())
        capture.feed(b"dbg: [script] [0] [I] P03_EXECUTOR_AI|P03_STAGE_V1|START_ENTERED|none\n")
        capture.feed(
            b"dbg: [script] [0] [I] P03_EXECUTOR_AI|P03_STAGE_V1|PLAN_FOUND|"
            + plan_hash(plan).encode()
            + b"\n"
        )
        capture.feed(
            b"dbg: [script] [0] [I] P03_EXECUTOR_AI|P03_STAGE_V1|WORLD_VALIDATION_STARTED|"
            + plan_hash(plan).encode()
            + b"\n"
        )
        ids = (
            [
                plan.routes[0].route_id,
                plan.fleet.groups[0].fleet_group_id,
                ",".join(action.construction_id for action in plan.infrastructure.actions),
            ]
            if status == "accepted"
            else ["", "", ""]
        )
        payload = "|".join(
            (
                "P03_EXECUTOR_AI",
                "P03_SETUP_V1",
                "1",
                "1",
                status,
                code,
                plan_hash(plan),
                scenario.world_fingerprint,
                scenario.world_manifest.source_digest,
                scenario.scenario_id,
                scenario.scenario_version,
                *ids,
            )
        )
        capture.feed(f"dbg: [script] [0] [I] {payload}\n".encode())
        result = parse_setup_evidence(capture.text, plan, scenario)
        assert result.status == status
        assert capture.trace.terminal_count == 1
    assert not list(tmp_path.glob("run-*"))


@pytest.mark.parametrize(
    "status,code", [("accepted", "NONE"), ("failed", "WORLD_RESOLUTION_FAILURE")]
)
@pytest.mark.parametrize("queued", [False, True])
def test_fake_child_p03_handshake_and_cleanup(
    tmp_path: Path, status: str, code: str, queued: bool
) -> None:
    plan, scenario = pinned_plan_and_scenario(WORLD_SOURCE)
    graphics = tmp_path / "opengfx-7.1.tar"
    graphics.write_bytes(b"controlled graphics archive")
    ids = (
        (
            plan.routes[0].route_id,
            plan.fleet.groups[0].fleet_group_id,
            ",".join(action.construction_id for action in plan.infrastructure.actions),
        )
        if status == "accepted"
        else ("", "", "")
    )
    terminal = "|".join(
        (
            "P03_EXECUTOR_AI",
            "P03_SETUP_V1",
            "1",
            "1",
            status,
            code,
            plan_hash(plan),
            scenario.world_fingerprint,
            scenario.world_manifest.source_digest,
            scenario.scenario_id,
            scenario.scenario_version,
            *ids,
        )
    )
    old_row = _fake_company_row(3, "Blue", "Old AI")
    new_row = _fake_company_row(1, "Red", "P03")
    script = (
        _FAKE_CONSOLE_INPUT
        + 'print("dbg: [net] Starting dedicated server, version 13.4", flush=True)\n'
        "assert sys.stdin.readline() == 'companies\\n'\n"
        f"print({old_row!r}, flush=True)\n"
        "assert sys.stdin.readline() == 'stop_ai 3\\n'\n"
        "print('AI stopped, company deleted.', flush=True)\n"
        "assert sys.stdin.readline() == 'companies\\n'\n"
        + (f"print({old_row!r}, flush=True)\n" if queued else "")
        + ("assert sys.stdin.readline() == 'companies\\n'\n" if queued else "")
        + "assert sys.stdin.readline() == 'start_ai P03ThinExecutor\\n'\n"
        "assert sys.stdin.readline() == 'companies\\n'\n"
        + ("" if queued else f"print({new_row!r}, flush=True)\n")
        + ("assert sys.stdin.readline() == 'companies\\n'\n" if queued else "")
        + (f"print({new_row!r}, flush=True)\n" if queued else "")
        + "assert sys.stdin.readline() == 'exec scripts/p03_unpause.scr\\n'\n"
        "print('__P03_UNPAUSE_ACK__', flush=True)\n"
        "print('dbg: [script] [1] [I] ' + "
        "'P03_EXECUTOR_AI|P03_STAGE_V1|START_ENTERED|none', flush=True)\n"
        "print('dbg: [script] [1] [I] ' + sys.argv[1], flush=True)\n"
    )
    with tempfile.TemporaryDirectory(dir=tmp_path, prefix="run-") as name:
        workspace = Path(name)
        workspace.chmod(0o700)
        prepare_proof_workspace(workspace, plan, scenario, WORLD_SOURCE, graphics)
        capture = SetupLogCapture(plan_hash(plan))
        with subprocess.Popen(
            (sys.executable, "-u", "-c", script, terminal),
            cwd=workspace,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
        ) as child:
            try:
                assert observe_setup_child(child, capture, 5)
            finally:
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.terminate()
                    child.wait(timeout=5)
            assert child.returncode == 0
        assert capture.trace.unpause_acknowledged
        assert capture.trace.start_entered
        assert capture.trace.terminal_count == 1
        assert capture.text.count(START_COMMAND) == 1
        assert capture.text.count(COMPANIES_COMMAND) == (5 if queued else 3)
        assert capture.text.index("AI stopped, company deleted.") < capture.text.index(
            START_COMMAND
        )
        assert capture.text.index(START_COMMAND) < capture.text.index(
            "Executing cmdline: 'exec scripts/p03_unpause.scr'"
        )
        assert parse_setup_evidence(capture.text, plan, scenario).status == status
    assert not list(tmp_path.glob("run-*"))


@pytest.mark.parametrize(
    "failure,initial_rows,stop_reply,expected",
    [
        ("no_ai", "", "", "expected one old AI company, found 0"),
        (
            "ambiguous",
            _fake_company_row(2, "Red", "Other AI"),
            "",
            "expected one old AI company, found 2",
        ),
        ("malformed", "#:broken company record", "", "malformed company listing"),
        ("rejected", "", "Unknown company. Company range is between 1 and 15.", "not acknowledged"),
    ],
)
def test_fake_child_rejects_unsafe_ai_isolation(
    failure: str, initial_rows: str, stop_reply: str, expected: str
) -> None:
    old_row = _fake_company_row(3, "Blue", "Old AI")
    rows = [old_row, initial_rows] if failure != "no_ai" else []
    script = (
        _FAKE_CONSOLE_INPUT
        + "assert sys.stdin.readline() == 'companies\\n'\n"
        + "".join(f"print({row!r}, flush=True)\n" for row in rows)
        + (
            f"assert sys.stdin.readline() == 'stop_ai 3\\n'\nprint({stop_reply!r}, flush=True)\n"
            if failure == "rejected"
            else "sys.stdin.readline()\n"
        )
    )
    capture = SetupLogCapture()
    with subprocess.Popen(
        (sys.executable, "-u", "-c", script),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
    ) as child:
        try:
            with pytest.raises(SetupEvidenceError, match=expected):
                observe_setup_child(child, capture, 5)
        finally:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=5)
    assert START_COMMAND not in capture.text
    assert "exec scripts/p03_unpause.scr" not in capture.text


def _controlled_prelaunch_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, SimpleNamespace]:
    root = tmp_path / "proof"
    root.mkdir()
    executable = tmp_path / "openttd-pinned"
    executable.write_bytes(b"fake executable; never run")
    graphics = tmp_path / "opengfx-7.1.tar"
    graphics.write_bytes(b"fake graphics archive")
    runtime = SimpleNamespace(
        executable_path=executable,
        opengfx_archive_path=graphics,
        provenance={"openttd_version": "13.4", "cache_identity": "openttd-13.4-pinned-v1"},
    )
    monkeypatch.setenv("P03_ARTIFACT_ROOT", str(root))
    monkeypatch.setenv("P03_ATTEMPT_NUMBER", "3")
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setenv("P03_RUNTIME_CACHE_ROOT", str(cache))
    monkeypatch.setattr(PinnedRuntimePreparer, "prepare", lambda *_args, **_kwargs: runtime)
    return root, runtime


def test_prelaunch_record_is_complete_before_fake_popen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, runtime = _controlled_prelaunch_context(tmp_path, monkeypatch)
    monkeypatch.setenv("P03_FAKE_SECRET", "must-not-be-recorded")

    class FakeLaunchReached(Exception):
        pass

    def fake_popen(argv: tuple[str, ...], **kwargs: object) -> None:
        record_path = root / "p03-proof-prelaunch.json"
        assert record_path.is_file()
        assert record_path.stat().st_mode & 0o777 == 0o400
        record = json.loads(record_path.read_text())
        assert record["prelaunch_schema_version"] == 1
        assert record["attempt_number"] == 3
        assert record["openttd_version"] == runtime.provenance["openttd_version"]
        assert record["openttd_version_source"] == "prepared_runtime.provenance.openttd_version"
        assert record["openttd_executable"] == str(runtime.executable_path)
        assert record["runtime_cache_identity"] == runtime.provenance["cache_identity"]
        assert tuple(record["argv"]) == argv
        assert record["popen"] == {
            "cwd": str(kwargs["cwd"]),
            **{key: kwargs[key] for key in ("stdin", "stdout", "stderr", "bufsize")},
        }
        assert kwargs["cwd"] == Path(record["owned_workspace"])
        assert record["child_environment"]["mode"] == "inherit"
        assert record["child_environment"]["overrides"] == {}
        assert "P03_FAKE_SECRET" not in record["child_environment"]["relevant_variables"]
        assert "must-not-be-recorded" not in record_path.read_text()
        assert record["artifact_root"] == str(root)
        assert record["artifact_root_fresh_at_start"] is True
        assert record["attempt2_root_distinct"] is True
        assert record["attempt2_artifact_file_count"] == ATTEMPT2_FILE_COUNT
        assert record["attempt2_artifact_digest"] == ATTEMPT2_DIGEST
        workspace = Path(record["owned_workspace"])
        package = workspace / "ai" / "P03ThinExecutor"
        assert record["ai_package"] == str(package)
        assert record["expected_ai_package_name"] == package.name
        assert (
            record["save_copy_sha256"]
            == hashlib.sha256(Path(record["save_copy"]).read_bytes()).hexdigest()
        )
        assert record["expected_plan_hash"] == plan_hash(pinned_plan_and_scenario(WORLD_SOURCE)[0])
        assert (
            record["expected_world_fingerprint"]
            == pinned_plan_and_scenario(WORLD_SOURCE)[1].world_fingerprint
        )
        assert record["staged_file_sha256"] == {
            name: hashlib.sha256((package / name).read_bytes()).hexdigest()
            for name in ("info.nut", "main.nut", "plan.nut")
        }
        assert (
            record["artifact_sha256"]
            == hashlib.sha256((workspace / "execution-plan.json").read_bytes()).hexdigest()
        )
        assert (
            record["package_sha256"]
            == hashlib.sha256(
                b"".join(
                    (package / name).read_bytes() for name in ("info.nut", "main.nut", "plan.nut")
                )
            ).hexdigest()
        )
        assert record["staged_symlinks"] == []
        assert not any(path.is_symlink() for path in workspace.rglob("*"))
        assert (
            record["configuration_sha256"]
            == hashlib.sha256((workspace / "openttd.cfg").read_bytes()).hexdigest()
        )
        assert record["configuration_text"] == (workspace / "openttd.cfg").read_text()
        assert (
            record["harness"]["game_start_script"]
            == (workspace / "scripts" / "game_start.scr").read_text()
        )
        assert (
            record["harness"]["unpause_script"]
            == (workspace / "scripts" / "p03_unpause.scr").read_text()
        )
        assert record["harness"]["observe_timeout_seconds"] == 45
        assert record["harness"]["max_company_polls"] == MAX_COMPANY_POLLS
        raise FakeLaunchReached

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    with pytest.raises(FakeLaunchReached):
        run_p03_proof()


def test_controlled_prelaunch_requires_no_checkout_proof_tree(tmp_path, monkeypatch):
    """All prior-proof inputs of an ordinary test must belong to its fixture."""
    root, _ = _controlled_prelaunch_context(tmp_path, monkeypatch)
    assert ATTEMPT2_ROOT.is_relative_to(tmp_path)
    record = run_p03_proof(prelaunch_only=True)
    assert record is not None
    assert record["attempt2_artifact_root"] == str(ATTEMPT2_ROOT)
    assert record["attempt2_artifact_file_count"] == ATTEMPT2_FILE_COUNT
    assert record["attempt2_artifact_digest"] == ATTEMPT2_DIGEST
    assert not list(root.glob("run-*"))


def test_controlled_cache_tests_never_use_official_downloads(tmp_path, monkeypatch):
    from app.simulation.openttd.runtime_assets import OfficialRuntimeSource

    def forbidden_fetch(*args, **kwargs):
        raise AssertionError("ordinary tests must not download runtime assets")

    # Forbid downloads before ANY setup, and simulate an absent checkout cache.
    monkeypatch.setattr(OfficialRuntimeSource, "fetch", forbidden_fetch)
    original_is_file = Path.is_file

    def without_checkout_cache(path):
        if "artifacts/experiments/cache" in str(path):
            return False
        return original_is_file(path)

    monkeypatch.setattr(Path, "is_file", without_checkout_cache)
    test_fresh_proof_uses_separate_cache_without_launch(tmp_path, monkeypatch)


def test_attempt2_digest_detects_fixture_mutation(tmp_path: Path) -> None:
    root = tmp_path / "old-proof-fixture"
    root.mkdir()
    (root / "log.txt").write_bytes(b"original")
    count, digest = _artifact_tree_digest(root)
    assert _verify_attempt2_artifacts(root, expected_count=count, expected_digest=digest) == (
        count,
        digest,
    )
    (root / "log.txt").write_bytes(b"changed")
    with pytest.raises(SetupEvidenceError, match="artifact digest mismatch"):
        _verify_attempt2_artifacts(root, expected_count=count, expected_digest=digest)


@pytest.mark.parametrize("failure", ["digest", "persist", "overwrite", "version", "identity"])
def test_prelaunch_failure_blocks_fake_popen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    root, runtime = _controlled_prelaunch_context(tmp_path, monkeypatch)
    reached = False

    def forbidden_popen(*_args: object, **_kwargs: object) -> None:
        nonlocal reached
        reached = True
        raise AssertionError("Popen must not be reached")

    monkeypatch.setattr(subprocess, "Popen", forbidden_popen)
    if failure == "digest":
        old_fixture = tmp_path / "mutated-old-proof"
        old_fixture.mkdir()
        for index in range(ATTEMPT2_FILE_COUNT):
            (old_fixture / f"proof-{index:03}.txt").write_bytes(b"changed")
        monkeypatch.setattr(sys.modules[__name__], "ATTEMPT2_ROOT", old_fixture)
        expected = "artifact digest mismatch"
    elif failure == "persist":

        def fail_link(*_args: object, **_kwargs: object) -> None:
            raise PermissionError("controlled prelaunch persistence failure")

        monkeypatch.setattr(os, "link", fail_link)
        expected = "controlled prelaunch persistence failure"
    elif failure == "overwrite":
        (root / "p03-proof-prelaunch.json").write_text("old retained proof")
        expected = "fresh artifact root"
    elif failure == "identity":
        runtime.provenance["cache_identity"] = "wrong-cache"
        expected = "runtime cache identity differs"
    else:
        runtime.provenance["openttd_version"] = "14.0"
        expected = "prepared OpenTTD version differs"
    with pytest.raises((SetupEvidenceError, PermissionError), match=expected):
        run_p03_proof()
    assert not reached
    if failure == "overwrite":
        assert (root / "p03-proof-prelaunch.json").read_text() == "old retained proof"


@pytest.mark.openttd
def test_one_real_p03_setup_proof(request: pytest.FixtureRequest) -> None:
    if not request.config.getoption("--run-openttd"):
        pytest.skip("pass --run-openttd for the single P03 transport proof")
    run_p03_proof()


def run_p03_proof(*, prelaunch_only: bool = False) -> dict | None:
    """Use the identical preparation boundary for deterministic and live proof."""
    attempt_value = os.environ.get("P03_ATTEMPT_NUMBER", "")
    if not attempt_value.isdecimal() or int(attempt_value) < 1:
        raise SetupEvidenceError("P03_ATTEMPT_NUMBER must be a positive integer")
    attempt_number = int(attempt_value)
    root_value = os.environ.get("P03_ARTIFACT_ROOT")
    assert root_value is not None
    root = Path(root_value)
    assert root.is_absolute() and root.is_dir() and not root.is_symlink()
    root_identity = root.resolve()
    attempt2_identity = ATTEMPT2_ROOT.resolve()
    if (
        root_identity == attempt2_identity
        or root_identity.is_relative_to(attempt2_identity)
        or attempt2_identity.is_relative_to(root_identity)
    ):
        raise SetupEvidenceError("attempt #3 artifact root overlaps attempt #2")
    if any(root.iterdir()):
        raise SetupEvidenceError("use a fresh artifact root; proof files must not be overwritten")
    source = WORLD_SOURCE
    plan, scenario = pinned_plan_and_scenario(source)

    experiment_scenario = ScenarioConfig(identifier="tiny", version="1")
    planning, ai = SimpleRoadOnlyStrategy().configure(experiment_scenario)
    config = ExperimentConfig(
        scenario=experiment_scenario,
        planning=planning,
        ai=ai,
        openttd_version="13.4",
        opengfx_version="7.1",
        seed=17,
        duration_days=1,
    )
    cache_value = os.environ.get("P03_RUNTIME_CACHE_ROOT", "")
    cache = Path(cache_value)
    if not cache_value or not cache.is_absolute() or cache.is_symlink():
        raise SetupEvidenceError("P03_RUNTIME_CACHE_ROOT must be an absolute independent cache")
    cache = cache.resolve()
    for protected in (root_identity, attempt2_identity):
        if cache == protected or cache.is_relative_to(protected) or protected.is_relative_to(cache):
            raise SetupEvidenceError("runtime cache overlaps proof artifacts")
    runtime = PinnedRuntimePreparer(cache).prepare(
        config, acquisition_policy=AcquisitionPolicy.CACHE_ONLY
    )
    assert runtime.executable_path.is_file() and runtime.opengfx_archive_path.is_file()
    if runtime.provenance.get("cache_identity") != "openttd-13.4-pinned-v1":
        raise SetupEvidenceError("runtime cache identity differs from pinned proof runtime")
    with tempfile.TemporaryDirectory(prefix="run-", dir=root) as directory:
        workspace = Path(directory)
        workspace.chmod(0o700)
        receipt, config_path, save = prepare_proof_workspace(
            workspace, plan, scenario, source, runtime.opengfx_archive_path
        )
        package = workspace / "ai" / "P03ThinExecutor"
        assert receipt.ai_directory == package
        assert receipt.module_path == package / "plan.nut"
        assert {path.name for path in package.iterdir()} == {"info.nut", "main.nut", "plan.nut"}
        source_package = Path(__file__).parent.parent / "app" / "planning" / "thin_ai"
        for name in ("info.nut", "main.nut"):
            assert (package / name).read_bytes() == (source_package / name).read_bytes()
        assert (package / "plan.nut").read_bytes() == transport_bytes(
            plan, scenario, receipt.plan_hash
        )
        assert receipt.artifact_path.read_bytes() == plan_artifact_bytes(plan)
        assert save.is_file() and save.read_bytes() == source.read_bytes()
        assert not any(path.is_symlink() for path in workspace.rglob("*"))
        assert (workspace / "scripts" / "game_start.scr").read_text() == (
            f"echo {HANDSHAKE_READY}\n"
        )
        assert (workspace / "scripts" / "p03_unpause.scr").read_text() == (
            f"unpause\necho {UNPAUSE_ACK}\n"
        )
        verify_staged_package(receipt)
        argv = (
            str(runtime.executable_path),
            "-D127.0.0.1:39891",
            "-g",
            str(save),
            "-I",
            "OpenGFX",
            "-d",
            "console=4,script=5",
            "-c",
            str(config_path),
            "-x",
            "-X",
        )
        popen_kwargs: _ProofPopenOptions = {
            "cwd": workspace,
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "bufsize": 0,
        }
        runtime_version = runtime.provenance.get("openttd_version")
        if runtime_version != config.openttd_version:
            raise SetupEvidenceError("prepared OpenTTD version differs from proof configuration")
        attempt2_count, attempt2_digest = _verify_attempt2_artifacts(ATTEMPT2_ROOT)
        prelaunch = {
            "prelaunch_schema_version": 1,
            "attempt_number": attempt_number,
            "artifact_root": str(root.absolute()),
            "artifact_root_fresh_at_start": True,
            "attempt2_artifact_root": str(ATTEMPT2_ROOT.absolute()),
            "attempt2_artifact_file_count": attempt2_count,
            "attempt2_artifact_digest": attempt2_digest,
            "attempt2_root_distinct": True,
            "owned_workspace": str(workspace.absolute()),
            "ai_package": str(package.absolute()),
            "expected_ai_package_name": package.name,
            "save_copy": str(save.absolute()),
            "save_source": str(source.absolute()),
            "expected_plan_hash": receipt.plan_hash,
            "expected_world_fingerprint": receipt.world_fingerprint,
            "manifest_world_fingerprint": receipt.world_fingerprint,
            "expected_runtime_world_hash": runtime_world_hash(
                runtime_projection_from_manifest(scenario.world_manifest)
            ),
            "runtime_observation_schema_version": 1,
            "world_source_digest": scenario.world_manifest.source_digest,
            "world_seed": scenario.seed,
            "world_dimensions": [scenario.width_tiles, scenario.height_tiles],
            "artifact_sha256": receipt.artifact_sha256,
            "module_sha256": receipt.module_sha256,
            "package_sha256": receipt.package_sha256,
            "staged_file_sha256": {
                name: hashlib.sha256((package / name).read_bytes()).hexdigest()
                for name in ("info.nut", "main.nut", "plan.nut")
            },
            "save_copy_sha256": hashlib.sha256(save.read_bytes()).hexdigest(),
            "staged_symlinks": [],
            "openttd_executable": str(runtime.executable_path.absolute()),
            "openttd_version": runtime_version,
            "openttd_version_source": "prepared_runtime.provenance.openttd_version",
            "runtime_cache_identity": runtime.provenance.get("cache_identity"),
            "runtime_cache_root": str(cache),
            "runtime_root": str(cache / "openttd-13.4-pinned-v1"),
            "runtime_provenance": json.loads(json.dumps(runtime.provenance)),
            "openttd_executable_sha256": hashlib.sha256(
                runtime.executable_path.read_bytes()
            ).hexdigest(),
            "acquisition_policy": AcquisitionPolicy.CACHE_ONLY.value,
            "runtime_available_before_launch": True,
            "argv": list(argv),
            "popen": {
                "cwd": str(popen_kwargs["cwd"]),
                "stdin": popen_kwargs["stdin"],
                "stdout": popen_kwargs["stdout"],
                "stderr": popen_kwargs["stderr"],
                "bufsize": popen_kwargs["bufsize"],
            },
            "child_environment": {
                "mode": "inherit",
                "overrides": {},
                "relevant_variables": {
                    key: os.environ[key]
                    for key in (
                        "HOME",
                        "XDG_DATA_HOME",
                        "XDG_CONFIG_HOME",
                        "XDG_CACHE_HOME",
                        "XDG_RUNTIME_DIR",
                        "LANG",
                        "LC_ALL",
                    )
                    if key in os.environ
                },
            },
            "configuration_text": config_path.read_text(encoding="ascii"),
            "configuration_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
            "harness": {
                "game_start_script": (workspace / "scripts" / "game_start.scr").read_text(
                    encoding="ascii"
                ),
                "game_start_script_sha256": hashlib.sha256(
                    (workspace / "scripts" / "game_start.scr").read_bytes()
                ).hexdigest(),
                "unpause_script": (workspace / "scripts" / "p03_unpause.scr").read_text(
                    encoding="ascii"
                ),
                "unpause_script_sha256": hashlib.sha256(
                    (workspace / "scripts" / "p03_unpause.scr").read_bytes()
                ).hexdigest(),
                "company_listing_command": "companies",
                "stop_command_template": "stop_ai <discovered-company-id>",
                "start_command": "start_ai P03ThinExecutor",
                "unpause_command": "exec scripts/p03_unpause.scr",
                "max_company_polls": MAX_COMPANY_POLLS,
                "company_poll_interval_seconds": COMPANY_POLL_INTERVAL_SECONDS,
                "observe_timeout_seconds": 45,
                "terminate_timeout_seconds": 10,
                "kill_timeout_seconds": 5,
            },
        }
        _persist_prelaunch_record(root, prelaunch)
        if prelaunch_only:
            return json.loads((root / "p03-proof-prelaunch.json").read_text())
        started = time.monotonic()
        capture = SetupLogCapture(plan_hash(plan))
        unpause_sent = False
        handshake_error: SetupEvidenceError | None = None
        with subprocess.Popen(
            argv,
            **popen_kwargs,
        ) as child:
            try:
                unpause_sent = observe_setup_child(child, capture, 45)
            except SetupEvidenceError as error:
                handshake_error = error
            finally:
                if child.poll() is None:
                    child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
                assert child.stdout is not None
                while remaining := os.read(child.stdout.fileno(), 65536):
                    capture.feed(remaining)
        log = capture.text
        (root / "p03-proof-log.txt").write_text(log, encoding="utf-8")
        trace = capture.trace
        (root / "p03-proof-diagnostics.json").write_text(
            json.dumps(
                {
                    "ai_selected": trace.ai_selected,
                    "old_ai_stopped": trace.old_ai_stopped,
                    "unpause_sent": unpause_sent,
                    "unpause_acknowledged": trace.unpause_acknowledged,
                    "api_compatibility_count": trace.api_compatibility_count,
                    "script_error_count": trace.script_error_count,
                    "script_crashes": [asdict(crash) for crash in trace.script_crashes],
                    "world_resolution_failures": [
                        asdict(failure) for failure in trace.world_resolution_failures
                    ],
                    "start_entered": trace.start_entered,
                    "plan_found": trace.plan_found,
                    "world_validation_started": trace.world_validation_started,
                    "terminal_count": trace.terminal_count,
                    "last_stage": trace.last_stage,
                    "process_exit_code": child.returncode,
                    "process_reaped": child.poll() is not None,
                },
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        if handshake_error is not None:
            raise handshake_error
        if trace.script_error_count:
            raise SetupEvidenceError(
                f"P03 script errors observed: {trace.script_error_count}; {trace.last_stage}"
            )
        if not trace.unpause_acknowledged:
            raise SetupEvidenceError(f"no P03 unpause acknowledgement; {trace.last_stage}")
        evidence = parse_setup_evidence(log, plan, scenario)
        script_messages = [
            match.group("message")
            for line in log.splitlines()
            if (match := re.fullmatch(r"dbg: \[script\] \[\d+\] \[I\] (?P<message>.*)", line))
            is not None
        ]
        expected_hash = plan_hash(plan)
        runtime_evidence = parse_runtime_world_evidence(
            log, runtime_projection_from_manifest(scenario.world_manifest), expected_hash
        )
        for marker in (
            f"P03_EXECUTOR_AI|P03_STAGE_V1|PLAN_DECODED|{expected_hash}",
            f"P03_EXECUTOR_AI|P03_STAGE_V1|WORLD_VALIDATION_SUCCEEDED|{expected_hash}",
        ):
            if script_messages.count(marker) != 1:
                raise SetupEvidenceError(f"expected exactly one runtime marker: {marker}")
        summary = {
            "plan_hash": receipt.plan_hash,
            "world_fingerprint": receipt.world_fingerprint,
            "world_source_digest": scenario.world_manifest.source_digest,
            "schema_version": plan.schema_version,
            "transport_version": 1,
            "ai_name": evidence.ai_name,
            "ai_version": evidence.ai_version,
            "module_sha256": receipt.module_sha256,
            "artifact_sha256": receipt.artifact_sha256,
            "package_sha256": receipt.package_sha256,
            "manifest_world_fingerprint": receipt.world_fingerprint,
            **runtime_evidence,
            "status": evidence.status,
            "failure_code": evidence.code.value,
            "route_ids": evidence.route_ids,
            "fleet_group_ids": evidence.fleet_group_ids,
            "infrastructure_action_ids": evidence.infrastructure_action_ids,
            "process_exit_code": child.returncode,
            "process_reaped": child.poll() is not None,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
        (root / "p03-proof-evidence.json").write_text(
            json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        assert evidence.status == "accepted"
    assert not list(root.glob("run-*"))
    with (root / "p03-proof-cleanup.json").open("x", encoding="utf-8") as stream:
        json.dump({"owned_workspace_removed": True, "process_reaped": True}, stream)
        stream.write("\n")


def test_fresh_proof_uses_separate_cache_without_launch(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    _prepare_controlled_runtime_cache(cache, monkeypatch)
    root = tmp_path / "proof"
    root.mkdir()
    monkeypatch.setenv("P03_ARTIFACT_ROOT", str(root))
    monkeypatch.setenv("P03_RUNTIME_CACHE_ROOT", str(cache))
    monkeypatch.setenv("P03_ATTEMPT_NUMBER", "3")

    class BoundaryReached(Exception):
        pass

    def fake_popen(argv, **kwargs):
        record = json.loads((root / "p03-proof-prelaunch.json").read_text())
        assert record["runtime_cache_root"] == str(cache)
        assert record["artifact_root"] == str(root)
        assert tuple(record["argv"]) == argv
        assert record["acquisition_policy"] == "cache_only"
        raise BoundaryReached

    from app.simulation.openttd.runtime_assets import OfficialRuntimeSource

    def forbidden_fetch(*args, **kwargs):
        raise AssertionError("CACHE_ONLY must not acquire assets")

    monkeypatch.setattr(OfficialRuntimeSource, "fetch", forbidden_fetch)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    with pytest.raises(BoundaryReached):
        run_p03_proof()


@pytest.mark.parametrize("failure", ["missing", "invalid", "overlap", "attempt2"])
def test_separate_cache_failure_blocks_popen(tmp_path, monkeypatch, failure):
    from app.simulation.openttd.runtime_assets import RuntimePreparationError

    cache = tmp_path / "cache"
    root = tmp_path / "proof"
    root.mkdir()
    if failure == "invalid":
        _prepare_controlled_runtime_cache(cache, monkeypatch)
        (cache / "openttd-13.4-pinned-v1/openttd/archive").write_bytes(b"corrupt")
    if failure == "overlap":
        cache = root / "cache"
    if failure == "attempt2":
        root = ATTEMPT2_ROOT
    monkeypatch.setenv("P03_ARTIFACT_ROOT", str(root))
    monkeypatch.setenv("P03_RUNTIME_CACHE_ROOT", str(cache))
    monkeypatch.setenv("P03_ATTEMPT_NUMBER", "3")

    def forbidden(*args, **kwargs):
        raise AssertionError("no process or acquisition permitted")

    from app.simulation.openttd.runtime_assets import OfficialRuntimeSource

    monkeypatch.setattr(OfficialRuntimeSource, "fetch", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    expected = {
        "missing": "missing asset",
        "invalid": "checksum mismatch",
        "overlap": "runtime cache overlaps",
        "attempt2": "artifact root overlaps",
    }[failure]
    with pytest.raises((RuntimePreparationError, SetupEvidenceError), match=expected):
        run_p03_proof()
    if failure != "attempt2":
        assert not (root / "p03-proof-prelaunch.json").exists()


_BUFFERED_CONSOLE_SCRIPT = r"""
import ctypes, select, sys
libc = ctypes.CDLL(None)
libc.fgets.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
libc.fgets.restype = ctypes.c_void_p
stdin = ctypes.c_void_p.in_dll(libc, 'stdin')
libc.setvbuf.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t]
stdio_buffer = ctypes.create_string_buffer(4096)
assert libc.setvbuf(stdin, stdio_buffer, 0, 4096) == 0
old = (
    "#:1(Red) Company Name: 'Old'  Year Founded: 1950  Money: 1  Loan: 0  "
    "Value: 1  (T:0, R:0, P:0, S:0) AI"
)
new = old.replace("'Old'", "'P03'")
print('__P03_HANDSHAKE_READY__', flush=True)
state = 'old'
while True:
    if not select.select([0], [], [], 0.1)[0]: continue
    buf = ctypes.create_string_buffer(1024)
    if not libc.fgets(buf, 1024, stdin): break
    cmd = buf.value.decode().strip()
    print("dbg: [console] Executing cmdline: '" + cmd + "'", flush=True)
    if cmd == 'stop_ai 1':
        state = 'empty'
        print('AI stopped, company deleted.', flush=True)
    elif cmd == 'companies':
        if state != 'empty': print(old if state == 'old' else new, flush=True)
    elif cmd.startswith('echo '): print(cmd[5:], flush=True)
    elif cmd == 'start_ai P03ThinExecutor': state = 'new'
    elif cmd == 'exec scripts/p03_unpause.scr':
        print('__P03_UNPAUSE_ACK__', flush=True)
        print('dbg: [script] [0] [I] P03_EXECUTOR_AI|P03_SETUP_V1|controlled', flush=True)
        break
"""


def _spawn_buffered_console() -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        (sys.executable, "-u", "-c", _BUFFERED_CONSOLE_SCRIPT),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
    )


def test_batched_console_input_stalls_after_stop() -> None:
    """The 13.4 select/fgets model strands commands buffered after stop_ai."""
    with _spawn_buffered_console() as child:
        assert child.stdin is not None
        assert child.stdout is not None
        try:
            assert child.stdout.readline().decode().strip() == HANDSHAKE_READY
            child.stdin.write(b"stop_ai 1\ncompanies\necho BATCH_END\n")
            child.stdin.flush()
            output = bytearray()
            deadline = time.monotonic() + 0.5
            while time.monotonic() < deadline:
                ready, _, _ = select.select([child.stdout], [], [], 0.05)
                if ready:
                    output.extend(os.read(child.stdout.fileno(), 65536))
            text_output = output.decode()
            assert "Executing cmdline: 'stop_ai 1'" in text_output
            assert "AI stopped, company deleted." in text_output
            assert "Executing cmdline: 'companies'" not in text_output
            assert "BATCH_END" not in text_output
        finally:
            child.terminate()
            child.wait(timeout=5)


def test_buffered_console_input_makes_handshake_progress() -> None:
    """Paced transport progresses through the same 13.4 select/fgets model."""
    capture = SetupLogCapture()
    with _spawn_buffered_console() as child:
        try:
            assert observe_setup_child(child, capture, 2)
        finally:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=5)
    assert START_COMMAND in capture.text
