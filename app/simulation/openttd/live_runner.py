"""One owned OpenTTD live process behind the synchronous SimulationRunner contract.

The final-result operation is mandatory until T09 supplies an explicit save/parser.
No production success path is available without it.
"""

import asyncio
import configparser
import os
import re
import signal
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from app.experiments.domain import (
    ExecutionFailure,
    ExecutionFailureCode,
    ExperimentConfig,
    LiveExecutionOptions,
    LiveExecutionSummary,
    SimulationExecutionError,
    SimulationResult,
    TelemetryStatus,
)
from app.simulation.openttd.admin_observer import (
    AdminObserver,
    ExpectedServerIdentity,
    ObserverEvent,
    ObserverHealth,
    ObserverMeasurement,
    ObserverState,
)
from app.simulation.openttd.live_launch import (
    LiveLaunchCode,
    LiveLaunchError,
    LiveLaunchPreparation,
    PreparedLiveRuntime,
)
from app.simulation.openttd.runtime_assets import (
    AcquisitionPolicy,
    PinnedRuntimePreparer,
    RuntimePreparationError,
)
from app.simulation.openttd.telemetry import GameDateObservation


@dataclass(frozen=True)
class LiveRunProgress:
    run_id: int
    artifact_dir: Path
    process_id: int
    configured_start_day: int
    observed_start_day: int
    target_day: int
    last_observed_day: int


class FinalResultOperation(Protocol):
    async def __call__(
        self,
        prepared: PreparedLiveRuntime,
        progress: LiveRunProgress,
        request_save: Callable[[], Awaitable[None]],
    ) -> SimulationResult: ...


class _Phase(StrEnum):
    PREPARING = "preparing"
    STARTING = "starting"
    CONNECTING = "connecting"
    RUNNING = "running"
    STOPPING = "stopping"
    FINALIZING = "finalizing"
    FINISHED = "finished"


class _RunFailure(Exception):
    def __init__(self, code: ExecutionFailureCode) -> None:
        self.code = code


_SOCKET_INODE = re.compile(r"socket:\[(\d+)\]\Z")


def _owned_endpoint_inodes(pid: int) -> set[str]:
    try:
        return {
            match.group(1)
            for descriptor in (Path("/proc") / str(pid) / "fd").iterdir()
            if (match := _SOCKET_INODE.fullmatch(os.readlink(descriptor)))
        }
    except OSError, PermissionError:
        return set()


def _matching_local_sockets(filename: str, port: int, inodes: set[str], *, tcp: bool) -> bool:
    try:
        for line in Path("/proc/net", filename).read_text().splitlines()[1:]:
            fields = line.split()
            address, encoded_port = fields[1].split(":")
            if (
                address == "0100007F"
                and int(encoded_port, 16) == port
                and fields[9] in inodes
                and (not tcp or fields[3] == "0A")
            ):
                return True
    except OSError, IndexError, ValueError:
        return False
    return False


def _owns_endpoints(pid: int, game_port: int, admin_port: int) -> bool:
    """Linux socket inode proof, independent of listening TCP availability alone."""
    inodes = _owned_endpoint_inodes(pid)
    return bool(inodes) and all(
        (
            _matching_local_sockets("tcp", game_port, inodes, tcp=True),
            _matching_local_sockets("udp", game_port, inodes, tcp=False),
            _matching_local_sockets("tcp", admin_port, inodes, tcp=True),
        )
    )


def _configured_start_day(path: Path) -> tuple[int, int, int]:
    main = configparser.ConfigParser()
    main.read(path)
    creation = main["game_creation"]
    year = int(creation.get("starting_year", "1950"))
    width = 1 << int(creation.get("map_x", "8"))
    height = 1 << int(creation.get("map_y", "8"))
    return date(year, 1, 1).toordinal() + 365, width, height


async def _drain(stream: asyncio.StreamReader) -> int:
    """Discard raw bytes after counting; no unbounded or credential-bearing logs."""
    count = 0
    while chunk := await stream.read(65536):
        count += len(chunk)
    return count


class LiveSimulationRunner:
    """Synchronous one-process runner; final parsing remains explicitly injected."""

    def __init__(
        self,
        assets: PinnedRuntimePreparer,
        launch: LiveLaunchPreparation,
        *,
        expected_identity: ExpectedServerIdentity,
        final_result: FinalResultOperation,
        options: LiveExecutionOptions | None = None,
        observer_factory: type[AdminObserver] = AdminObserver,
        cancellation: threading.Event | None = None,
    ) -> None:
        self.assets = assets
        self.launch = launch
        self.expected_identity = expected_identity
        self.final_result = final_result
        self.options = options or LiveExecutionOptions()
        self.observer_factory = observer_factory
        self.cancellation = cancellation

    def _check_cancellation(self) -> None:
        if self.cancellation is not None and self.cancellation.is_set():
            raise _RunFailure(ExecutionFailureCode.CANCELLED)

    @staticmethod
    def _close_prepared(prepared: PreparedLiveRuntime | None) -> tuple[str, ...]:
        if prepared is None or prepared.lease.closed:
            return ()
        try:
            prepared.close()
        except Exception:
            return ("workspace_or_lease_cleanup_failure",)
        return ()

    def run(self, config: ExperimentConfig, *, run_id: int, artifact_dir: Path) -> SimulationResult:
        started = time.monotonic()
        deadline = started + self.options.startup_timeout_seconds
        prepared: PreparedLiveRuntime | None = None
        try:
            self._check_cancellation()
            if time.monotonic() >= deadline:
                raise _RunFailure(ExecutionFailureCode.TIMEOUT)
            try:
                runtime = self.assets.prepare(
                    config,
                    deadline=deadline,
                    acquisition_policy=AcquisitionPolicy.CACHE_ONLY,
                )
            except RuntimePreparationError:
                code = (
                    ExecutionFailureCode.TIMEOUT
                    if time.monotonic() >= deadline
                    else ExecutionFailureCode.STARTUP_FAILURE
                )
                raise _RunFailure(code) from None
            self._check_cancellation()
            try:
                prepared = self.launch.prepare(config, runtime, deadline=deadline)
            except LiveLaunchError as exc:
                code = (
                    ExecutionFailureCode.TIMEOUT
                    if exc.code is LiveLaunchCode.DEADLINE_EXCEEDED
                    else ExecutionFailureCode.STARTUP_FAILURE
                )
                raise _RunFailure(code) from None
            self._check_cancellation()
            start_day, width, height = _configured_start_day(prepared.main_config_path)
            if (
                self.expected_identity.revision != "OpenTTD 13.4"
                or self.expected_identity.seed != config.seed
                or self.expected_identity.width != width
                or self.expected_identity.height != height
            ):
                raise _RunFailure(ExecutionFailureCode.PROTOCOL_FAILURE)
            if time.monotonic() >= deadline:
                raise _RunFailure(ExecutionFailureCode.TIMEOUT)
            return asyncio.run(
                self._execute(config, prepared, run_id, artifact_dir, start_day, deadline)
            )
        except _RunFailure as exc:
            raise self._failure(exc.code, cleanup=self._close_prepared(prepared)) from None
        except KeyboardInterrupt:
            raise self._failure(
                ExecutionFailureCode.CANCELLED, cleanup=self._close_prepared(prepared)
            ) from None
        except SimulationExecutionError:
            raise
        except Exception:
            raise self._failure(
                ExecutionFailureCode.STARTUP_FAILURE, cleanup=self._close_prepared(prepared)
            ) from None

    @staticmethod
    def _failure(
        code: ExecutionFailureCode,
        *,
        last_day: int | None = None,
        exit_code: int | None = None,
        cleanup: tuple[str, ...] = (),
    ) -> SimulationExecutionError:
        return SimulationExecutionError(
            ExecutionFailure(
                code=code,
                message=code.value.replace("_", " "),
                last_observed_day=last_day,
                process_exit_code=exit_code,
                cleanup_diagnostics=cleanup,
            )
        )

    async def _execute(
        self,
        config: ExperimentConfig,
        prepared: PreparedLiveRuntime,
        run_id: int,
        artifact_dir: Path,
        start_day: int,
        startup_deadline: float,
    ) -> SimulationResult:
        phase = _Phase.STARTING
        process: asyncio.subprocess.Process | None = None
        observer_task: asyncio.Task[None] | None = None
        process_wait: asyncio.Task[int] | None = None
        drains: tuple[asyncio.Task[int], ...] = ()
        failure: ExecutionFailureCode | None = None
        diagnostics: list[str] = []
        result: SimulationResult | None = None
        first_day: int | None = None
        last_day: int | None = None
        target_day = start_day + config.duration_days
        observer_failure: ExecutionFailureCode | None = None
        ready = False
        quit_requested = False
        changed = asyncio.Event()

        def emit(event: ObserverEvent) -> None:
            nonlocal ready, first_day, last_day, observer_failure
            if isinstance(event, ObserverMeasurement) and isinstance(
                event.payload, GameDateObservation
            ):
                last_day = event.payload.game_day
                if first_day is None:
                    first_day = last_day
            elif isinstance(event, ObserverHealth):
                if event.state is ObserverState.READY:
                    ready = True
                elif not quit_requested:
                    observer_failure = {
                        ObserverState.AUTHENTICATION_REJECTED: (
                            ExecutionFailureCode.AUTHENTICATION_FAILURE
                        ),
                        ObserverState.PROTOCOL_REJECTED: ExecutionFailureCode.PROTOCOL_FAILURE,
                        ObserverState.MALFORMED_PACKET: ExecutionFailureCode.PROTOCOL_FAILURE,
                        ObserverState.CONNECTION_REJECTED: ExecutionFailureCode.STARTUP_FAILURE,
                        ObserverState.SERVER_SHUTDOWN: ExecutionFailureCode.UNEXPECTED_SHUTDOWN,
                        ObserverState.WORLD_RESET: ExecutionFailureCode.UNEXPECTED_SHUTDOWN,
                        ObserverState.EOF: ExecutionFailureCode.UNEXPECTED_SHUTDOWN,
                        ObserverState.CONNECTION_LOST: ExecutionFailureCode.OBSERVER_LOST,
                        ObserverState.HEARTBEAT_FAILURE: ExecutionFailureCode.OBSERVER_LOST,
                    }.get(event.state, observer_failure)
            changed.set()

        async def wait_change(deadline: float) -> None:
            while True:
                self._check_cancellation()
                changed.clear()
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise _RunFailure(ExecutionFailureCode.TIMEOUT)
                try:
                    await asyncio.wait_for(changed.wait(), min(remaining, 0.05))
                    return
                except TimeoutError:
                    continue

        try:
            self._check_cancellation()
            process = await asyncio.create_subprocess_exec(
                *prepared.argv,
                cwd=prepared.cwd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            assert process.stdin is not None and process.stdout is not None
            assert process.stderr is not None
            drains = (
                asyncio.create_task(_drain(process.stdout)),
                asyncio.create_task(_drain(process.stderr)),
            )
            process_wait = asyncio.create_task(process.wait())
            process_wait.add_done_callback(lambda _: changed.set())
            loop = asyncio.get_running_loop()
            endpoint_deadline = loop.time() + max(0, startup_deadline - time.monotonic())
            while not _owns_endpoints(process.pid, prepared.game_port, prepared.admin_port):
                self._check_cancellation()
                if process.returncode is not None:
                    raise _RunFailure(ExecutionFailureCode.UNEXPECTED_SHUTDOWN)
                if loop.time() >= endpoint_deadline:
                    raise _RunFailure(ExecutionFailureCode.TIMEOUT)
                await asyncio.sleep(min(0.025, endpoint_deadline - loop.time()))
            phase = _Phase.CONNECTING
            observer = self.observer_factory(
                "127.0.0.1",
                prepared.admin_port,
                prepared.admin_password,
                "softdev2-live",
                "1",
                self.expected_identity,
                connect_timeout=min(10.0, self.options.handshake_timeout_seconds),
                handshake_timeout=self.options.handshake_timeout_seconds,
                heartbeat_interval=self.options.heartbeat_interval_seconds,
                heartbeat_timeout=self.options.heartbeat_timeout_seconds,
            )
            observer_task = asyncio.create_task(observer.run(emit))
            observer_task.add_done_callback(lambda _: changed.set())
            readiness_deadline = min(
                endpoint_deadline, loop.time() + self.options.handshake_timeout_seconds
            )
            while not ready:
                if observer_failure is not None:
                    raise _RunFailure(observer_failure)
                if process.returncode is not None:
                    raise _RunFailure(ExecutionFailureCode.UNEXPECTED_SHUTDOWN)
                if observer_task.done():
                    raise _RunFailure(ExecutionFailureCode.UNEXPECTED_SHUTDOWN)
                await wait_change(readiness_deadline)
            if observer_failure is not None or first_day is None or process.returncode is not None:
                raise _RunFailure(observer_failure or ExecutionFailureCode.UNEXPECTED_SHUTDOWN)
            self._check_cancellation()
            await self._command(process, "unpause")
            phase = _Phase.RUNNING
            running_seconds = self.options.running_timeout_seconds or max(
                300, 5 * config.duration_days
            )
            running_deadline = loop.time() + running_seconds
            while last_day is None or last_day < target_day:
                if observer_failure is not None:
                    raise _RunFailure(observer_failure)
                if process.returncode is not None or observer_task.done():
                    raise _RunFailure(ExecutionFailureCode.UNEXPECTED_SHUTDOWN)
                await wait_change(running_deadline)
            if observer_failure is not None:
                raise _RunFailure(observer_failure)
            self._check_cancellation()
            phase = _Phase.STOPPING
            await self._command(process, "pause")
            assert first_day is not None and last_day is not None
            progress = LiveRunProgress(
                run_id,
                artifact_dir,
                process.pid,
                start_day,
                first_day,
                target_day,
                last_day,
            )

            async def request_save() -> None:
                await self._command(process, "save", prepared.final_save_path.name)

            phase = _Phase.FINALIZING
            final_task = asyncio.create_task(self.final_result(prepared, progress, request_save))
            try:
                final_deadline = loop.time() + self.options.final_parse_timeout_seconds
                while not final_task.done():
                    self._check_cancellation()
                    if observer_failure is not None or process.returncode is not None:
                        raise _RunFailure(
                            observer_failure or ExecutionFailureCode.UNEXPECTED_SHUTDOWN
                        )
                    remaining = final_deadline - loop.time()
                    if remaining <= 0:
                        raise _RunFailure(ExecutionFailureCode.FINALIZATION_FAILURE)
                    await asyncio.wait({final_task}, timeout=min(remaining, 0.05))
                self._check_cancellation()
                result = final_task.result()
                if not isinstance(result, SimulationResult):
                    raise TypeError("final result provider returned an invalid result")
            except _RunFailure:
                raise
            except Exception:
                raise _RunFailure(ExecutionFailureCode.FINALIZATION_FAILURE) from None
            finally:
                if not final_task.done():
                    final_task.cancel()
                    await asyncio.wait_for(asyncio.gather(final_task, return_exceptions=True), 2)
            if observer_failure is not None or process.returncode is not None:
                raise _RunFailure(observer_failure or ExecutionFailureCode.UNEXPECTED_SHUTDOWN)
            quit_requested = True
            await self._command(process, "quit")
            quit_deadline = loop.time() + self.options.shutdown_timeout_seconds
            while process.returncode is None:
                self._check_cancellation()
                await wait_change(quit_deadline)
            if process.returncode != 0:
                raise _RunFailure(ExecutionFailureCode.UNEXPECTED_SHUTDOWN)
            phase = _Phase.FINISHED
        except _RunFailure as exc:
            failure = exc.code
        except asyncio.CancelledError:
            failure = ExecutionFailureCode.CANCELLED
        except Exception:
            failure = (
                ExecutionFailureCode.FINALIZATION_FAILURE
                if phase is _Phase.FINALIZING
                else ExecutionFailureCode.STARTUP_FAILURE
            )
        finally:
            if process is not None:
                if process.returncode is None:
                    try:
                        if not quit_requested:
                            await self._command(process, "quit")
                        assert process_wait is not None
                        await asyncio.wait_for(
                            asyncio.shield(process_wait), self.options.shutdown_timeout_seconds
                        )
                    except Exception:
                        pass
                if process.returncode is None:
                    try:
                        await self._signal_and_wait(
                            process, signal.SIGTERM, self.options.terminate_timeout_seconds
                        )
                    except Exception:
                        diagnostics.append("owned_process_term_error")
                if process.returncode is None:
                    try:
                        await self._signal_and_wait(
                            process, signal.SIGKILL, self.options.kill_timeout_seconds
                        )
                    except Exception:
                        diagnostics.append("owned_process_kill_error")
                if process.returncode is None:
                    diagnostics.append("owned_process_not_reaped")
            if observer_task is not None:
                if not observer_task.done():
                    observer_task.cancel()
                try:
                    await asyncio.wait_for(asyncio.gather(observer_task, return_exceptions=True), 2)
                except Exception:
                    diagnostics.append("observer_cleanup_timeout")
            for task in drains:
                if not task.done():
                    task.cancel()
            if drains:
                try:
                    await asyncio.wait_for(asyncio.gather(*drains, return_exceptions=True), 2)
                except Exception:
                    diagnostics.append("log_cleanup_timeout")
            if process_wait is not None and not process_wait.done():
                process_wait.cancel()
                try:
                    await asyncio.wait_for(asyncio.gather(process_wait, return_exceptions=True), 2)
                except Exception:
                    diagnostics.append("process_wait_cleanup_timeout")
            if process is None or process.returncode is not None:
                try:
                    prepared.close()
                except Exception:
                    diagnostics.append("workspace_or_lease_cleanup_failure")
            if diagnostics and failure is None:
                failure = ExecutionFailureCode.CLEANUP_FAILURE
        if failure is not None:
            raise self._failure(
                failure,
                last_day=last_day,
                exit_code=process.returncode if process is not None else None,
                cleanup=tuple(diagnostics),
            )
        assert process is not None and result is not None and last_day is not None
        return result.model_copy(
            update={
                "live_summary": LiveExecutionSummary(
                    telemetry_status=TelemetryStatus.INCOMPLETE,
                    last_observed_day=last_day,
                    requested_target_day=target_day,
                    process_exit_code=process.returncode,
                    cleanup_succeeded=True,
                )
            }
        )

    async def _command(
        self, process: asyncio.subprocess.Process, action: str, save_name: str | None = None
    ) -> None:
        if action not in {"pause", "unpause", "save", "quit"}:
            raise _RunFailure(ExecutionFailureCode.PROTOCOL_FAILURE)
        if action == "save":
            if save_name is None or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.sav", save_name):
                raise _RunFailure(ExecutionFailureCode.FINALIZATION_FAILURE)
            command = f"save {save_name}\n"
        else:
            command = action + "\n"
        if process.stdin is None or process.stdin.is_closing():
            raise _RunFailure(ExecutionFailureCode.UNEXPECTED_SHUTDOWN)
        try:
            process.stdin.write(command.encode("ascii"))
            await asyncio.wait_for(process.stdin.drain(), self.options.shutdown_timeout_seconds)
        except TimeoutError:
            raise _RunFailure(ExecutionFailureCode.TIMEOUT) from None
        except OSError:
            raise _RunFailure(ExecutionFailureCode.UNEXPECTED_SHUTDOWN) from None

    @staticmethod
    async def _signal_and_wait(
        process: asyncio.subprocess.Process, requested: signal.Signals, timeout: float
    ) -> None:
        if process.returncode is not None:
            return
        try:
            if os.getpgid(process.pid) != process.pid:
                return
            os.killpg(process.pid, requested)
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), timeout)
        except TimeoutError:
            pass
