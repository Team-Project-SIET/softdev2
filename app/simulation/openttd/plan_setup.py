"""Paced P03 console isolation and P06 setup gate on the live runner's sole reader."""

import asyncio
import re
import time
from pathlib import Path

from app.experiments.domain import ExecutionFailureCode
from app.experiments.plan_evaluation import PlanEvaluationInput, accept_execution, retain_bytes
from app.planning.canonical import canonical_bytes
from app.planning.execution_evidence import ExecutionReceipt, parse_execution_evidence
from app.planning.setup_evidence import SetupLogCapture


class PlanSetupFailure(ValueError):
    def __init__(self, code: ExecutionFailureCode):
        self.code = code
        super().__init__(code.value)


class PlanSetup:
    """One instance, one immutable input, one terminal; never reads stdout itself."""

    def __init__(self, value: PlanEvaluationInput):
        self.value = value
        self.capture = SetupLogCapture()
        self.changed = asyncio.Event()
        self.receipt: ExecutionReceipt | None = None
        self.observed_start_day: int | None = None
        self._bytes = 0
        self.failure_code: ExecutionFailureCode | None = None

    def feed(self, chunk: bytes):
        self._bytes += len(chunk)
        if self._bytes > 1024 * 1024:
            self.failure_code = ExecutionFailureCode.PLAN_TRANSPORT_FAILURE
        else:
            self.capture.feed(chunk)
        self.changed.set()

    async def execute(self, process, directory: Path, deadline: float, check_health=None):
        async def wait(predicate):
            if check_health is not None:
                check_health()
            while not predicate():
                if check_health is not None:
                    check_health()
                if self.failure_code is not None:
                    raise PlanSetupFailure(self.failure_code)
                if self.capture.trace.script_crashes or self.capture.trace.script_error_count:
                    raise PlanSetupFailure(ExecutionFailureCode.PLAN_SETUP_FAILURE)
                if process.returncode is not None or time.monotonic() >= deadline:
                    raise PlanSetupFailure(ExecutionFailureCode.PLAN_TRANSPORT_FAILURE)
                self.changed.clear()
                try:
                    await asyncio.wait_for(
                        self.changed.wait(), min(0.05, max(0.001, deadline - time.monotonic()))
                    )
                except TimeoutError:
                    pass

        async def command(text: str, *markers: str):
            if check_health is not None:
                check_health()
            before = len(self.capture.text.splitlines())
            process.stdin.write((text + "\n").encode("ascii"))
            await process.stdin.drain()
            expected = (f"dbg: [console] Executing cmdline: '{text}'", *markers)
            await wait(
                lambda: all(
                    marker in self.capture.text.splitlines()[before:] for marker in expected
                )
            )

        async def companies(label: str):
            await command(f"echo {label}_BEGIN", f"{label}_BEGIN")
            await command("companies")
            await command(f"echo {label}_END", f"{label}_END")
            lines = self.capture.text.splitlines()
            subset = lines[lines.index(f"{label}_BEGIN") + 1 : lines.index(f"{label}_END")]
            result = {}
            for line in subset:
                match = re.fullmatch(
                    r"#:(?P<id>[1-9]|1[0-5])\([^)]*\) Company Name: '.*'  Year Founded: .*  "
                    r"\(T:\d+, R:\d+, P:\d+, S:\d+\) (?P<owner>AI|unprotected|protected)?",
                    line,
                )
                if line.startswith("#:") and match is None:
                    raise PlanSetupFailure(ExecutionFailureCode.PLAN_TRANSPORT_FAILURE)
                if match:
                    number = int(match["id"])
                    if number in result:
                        raise PlanSetupFailure(ExecutionFailureCode.PLAN_TRANSPORT_FAILURE)
                    result[number] = match["owner"] == "AI"
            return result

        try:
            await wait(lambda: "__P03_HANDSHAKE_READY__" in self.capture.text.splitlines())
            existing = await companies("__P07_DISCOVER__")
            old = [number for number, ai in existing.items() if ai]
            if len(old) != 1 or len(existing) != 1:
                raise PlanSetupFailure(ExecutionFailureCode.PLAN_TRANSPORT_FAILURE)
            await command(f"stop_ai {old[0]}", "AI stopped, company deleted.")
            for poll in range(40):
                current = await companies(f"__P07_STOP_{poll:02d}__")
                if old[0] not in current:
                    break
                await asyncio.sleep(0.1)
            else:
                raise PlanSetupFailure(ExecutionFailureCode.PLAN_TRANSPORT_FAILURE)
            if current:
                raise PlanSetupFailure(ExecutionFailureCode.PLAN_TRANSPORT_FAILURE)
            await command("start_ai P03ThinExecutor")
            for poll in range(40):
                current = await companies(f"__P07_START_{poll:02d}__")
                if current == {1: True}:
                    break
                if sum(current.values()) > 1:
                    raise PlanSetupFailure(ExecutionFailureCode.PLAN_TRANSPORT_FAILURE)
                await asyncio.sleep(0.1)
            else:
                raise PlanSetupFailure(ExecutionFailureCode.PLAN_TRANSPORT_FAILURE)
            await command("exec scripts/p03_unpause.scr", "__P03_UNPAUSE_ACK__")
            await wait(lambda: "P06_EXECUTION_V1|" in self.capture.text)
            self.receipt = parse_execution_evidence(
                self.capture.text, self.value.plan, self.value.scenario, self.value.bindings
            )
            if self.receipt.code == "PARTIAL_EXECUTION":
                raise PlanSetupFailure(ExecutionFailureCode.PARTIAL_EXECUTION)
            self.receipt = accept_execution(self.value, self.capture.text)
        except PlanSetupFailure:
            raise
        except ValueError:
            raise PlanSetupFailure(ExecutionFailureCode.PLAN_SETUP_FAILURE) from None
        finally:
            retain_bytes(self.capture.text.encode(), directory, "setup-evidence.log")
            if self.receipt is not None:
                retain_bytes(canonical_bytes(self.receipt), directory, "execution-receipt.json")

    def finalize_evidence(self, directory: Path) -> None:
        retain_bytes(self.capture.text.encode(), directory, "execution-evidence.log")
        if self.failure_code is not None:
            raise PlanSetupFailure(self.failure_code)
        if self.receipt is not None and self.receipt.result == "success":
            if self.capture.trace.script_crashes or self.capture.trace.script_error_count:
                raise PlanSetupFailure(ExecutionFailureCode.PLAN_SETUP_FAILURE)
            try:
                if accept_execution(self.value, self.capture.text) != self.receipt:
                    raise ValueError("receipt changed after setup")
            except ValueError:
                raise PlanSetupFailure(ExecutionFailureCode.PLAN_SETUP_FAILURE) from None
