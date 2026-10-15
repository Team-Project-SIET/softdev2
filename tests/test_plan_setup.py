"""P03 pacing/P06 gating on one controlled console stream, without a process."""

import asyncio
import time
from types import SimpleNamespace

import pytest

from app.experiments.domain import ExecutionFailureCode
from app.simulation.openttd.plan_setup import PlanSetup, PlanSetupFailure
from tests.test_plan_evaluation import request
from tests.test_planning_execution import run_executor


class Console:
    def __init__(self, setup, *, failure=None, bad_listing=False):
        self.setup = setup
        self.commands = []
        self.phase = "old"
        self.failure = failure
        self.bad_listing = bad_listing
        self.pending = False

    def write(self, data):
        assert not self.pending, "unsafe console batching"
        self.pending = True
        self.commands.append(data.decode().strip())

    async def drain(self):
        cmd = self.commands[-1]
        self.setup.feed(f"dbg: [console] Executing cmdline: '{cmd}'\n".encode())
        if cmd.startswith("echo "):
            self.setup.feed((cmd[5:] + "\n").encode())
        elif cmd == "companies":
            if self.bad_listing:
                self.setup.feed(b"#:malformed\n")
            elif self.phase != "empty":
                self.setup.feed(
                    b"#:1(Test) Company Name: 'Test'  Year Founded: 1950  (T:0, R:0, P:0, S:0) AI\n"
                )
        elif cmd.startswith("stop_ai"):
            self.phase = "empty"
            self.setup.feed(b"AI stopped, company deleted.\n")
        elif cmd.startswith("start_ai"):
            self.phase = "new"
        elif cmd == "exec scripts/p03_unpause.scr":
            self.setup.feed(b"__P03_UNPAUSE_ACK__\n")
            v = self.setup.value
            log, _ = run_executor(v.plan, v.scenario, v.bindings, fail=self.failure)
            self.setup.feed(log.encode())
        self.pending = False
        await asyncio.sleep(0)


@pytest.mark.parametrize("failure", [None, "road_station", "purchase", "order"])
def test_paced_setup_terminal_gate(tmp_path, failure):
    setup = PlanSetup(request())
    console = Console(setup, failure=failure)
    setup.feed(b"__P03_HANDSHAKE_READY__\n")

    async def execute():
        await setup.execute(
            SimpleNamespace(stdin=console, returncode=None), tmp_path, time.monotonic() + 2
        )

    if failure is None:
        asyncio.run(execute())
        assert setup.receipt is not None
        assert setup.receipt.result == "success"
    else:
        with pytest.raises(PlanSetupFailure) as caught:
            asyncio.run(execute())
        assert caught.value.code == ExecutionFailureCode.PARTIAL_EXECUTION
    assert console.commands.count("start_ai P03ThinExecutor") == 1
    assert console.commands[-1] == "exec scripts/p03_unpause.scr"
    assert (tmp_path / "setup-evidence.log").exists()


def test_bad_company_evidence_stops_before_start(tmp_path):
    setup = PlanSetup(request())
    console = Console(setup, bad_listing=True)
    setup.feed(b"__P03_HANDSHAKE_READY__\n")
    with pytest.raises(PlanSetupFailure):
        asyncio.run(
            setup.execute(
                SimpleNamespace(stdin=console, returncode=None), tmp_path, time.monotonic() + 1
            )
        )
    assert not any(cmd.startswith("start_ai") for cmd in console.commands)


def test_duplicate_terminal_after_setup_rejected(tmp_path):
    setup = PlanSetup(request())
    console = Console(setup)
    setup.feed(b"__P03_HANDSHAKE_READY__\n")
    asyncio.run(
        setup.execute(
            SimpleNamespace(stdin=console, returncode=None), tmp_path, time.monotonic() + 2
        )
    )
    line = next(line for line in setup.capture.text.splitlines() if "P06_EXECUTION_V1|" in line)
    setup.feed((line + "\n").encode())
    with pytest.raises(PlanSetupFailure):
        setup.finalize_evidence(tmp_path)


def test_health_guard_stops_before_another_console_command(tmp_path):
    setup = PlanSetup(request())
    console = Console(setup)
    setup.feed(b"__P03_HANDSHAKE_READY__\n")
    checks = 0

    def health():
        nonlocal checks
        checks += 1
        if checks == 3:
            raise RuntimeError("observer lost")

    with pytest.raises(RuntimeError, match="observer lost"):
        asyncio.run(
            setup.execute(
                SimpleNamespace(stdin=console, returncode=None),
                tmp_path,
                time.monotonic() + 1,
                health,
            )
        )
    assert len(console.commands) == 1
    assert not any(cmd.startswith("start_ai") for cmd in console.commands)
