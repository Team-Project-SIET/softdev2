"""Run-local observation ordering and bounded async persistence, without process authority."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from app.experiments.telemetry_repository import (
    TelemetryBatch,
    TelemetryProgress,
    TelemetryStorageError,
    TransientStorageError,
)
from app.simulation.openttd.admin_observer import (
    CompanyLifecycleKind,
    ObserverCompanyLifecycle,
    ObserverEvent,
    ObserverHealth,
    ObserverMeasurement,
    ObserverState,
    ObserverUnknownPacket,
)
from app.simulation.openttd.telemetry import (
    CompanyEconomyObservation,
    CompanyInfoObservation,
    CompanyStatsObservation,
    DateQuality,
    DiagnosticCode,
    DiagnosticSeverity,
    DiagnosticSummary,
    GameDateObservation,
    ObservationKind,
    ObservationPayload,
    ObservationSource,
    TelemetryDiagnostic,
    TelemetryObservation,
)


class AsyncTelemetryStore(Protocol):
    async def write_batch(self, batch: TelemetryBatch, *, deadline: float) -> None: ...
    async def close(self) -> None: ...


class StorageHealthCode(StrEnum):
    OVERLOADED = "telemetry_queue_full"
    RETRY_EXHAUSTED = "telemetry_retry_exhausted"
    PERMANENT_FAILURE = "telemetry_integrity_or_validation_failure"
    FLUSH_TIMEOUT = "telemetry_flush_timeout"
    CANCELLED = "telemetry_writer_cancelled"


@dataclass(frozen=True)
class StorageHealth:
    code: StorageHealthCode
    received_count: int
    persisted_count: int
    unpersisted_count: int


class TelemetryPipelineFailed(RuntimeError):
    def __init__(self, health: StorageHealth) -> None:
        self.health = health
        super().__init__(health.code.value)


_PAYLOAD_KINDS = {
    GameDateObservation: ObservationKind.DATE,
    CompanyInfoObservation: ObservationKind.COMPANY_INFO,
    CompanyEconomyObservation: ObservationKind.COMPANY_ECONOMY,
    CompanyStatsObservation: ObservationKind.COMPANY_STATS,
    TelemetryDiagnostic: ObservationKind.DIAGNOSTIC,
}


class TelemetryProcessor:
    """One event-loop owner. emit() never waits for storage or invokes lifecycle code.

    start/emit/close are used in one async scope. A separate wait_fatal() signal
    remains available when the 1024 total queued/in-flight slots are exhausted.
    Failure retains unpersisted observations and reports their count; it never
    turns an emptied queue into a claim of complete telemetry coverage.
    """

    CAPACITY = 1024
    BATCH_SIZE = 100
    FLUSH_SECONDS = 1.0
    RETRY_SECONDS = 10.0

    def __init__(
        self,
        run_id: int,
        repository: AsyncTelemetryStore,
        *,
        utc_now: Callable[[], datetime] = lambda: datetime.now(UTC),
        retry_budget: float = RETRY_SECONDS,
        flush_timeout: float = 30.0,
    ) -> None:
        if (
            type(run_id) is not int
            or run_id <= 0
            or not 0 < retry_budget <= 10
            or flush_timeout <= 0
        ):
            raise ValueError("invalid telemetry processor configuration")
        self.run_id = run_id
        self.repository = repository
        self.utc_now = utc_now
        self.retry_budget = retry_budget
        self.flush_timeout = flush_timeout
        self._queue: asyncio.Queue[tuple[TelemetryObservation, float]] = asyncio.Queue(
            self.CAPACITY
        )
        self._wake = asyncio.Event()
        self._health_ready = asyncio.Event()
        self._writer: asyncio.Task[None] | None = None
        self._closing = False
        self._sequence = 0
        self._epoch = 0
        self._protocol: int | None = None
        self._date: tuple[int, int] | None = None
        self._last_day: int | None = None
        self._missing_reported = False
        self._unknown = 0
        self._gaps = 0
        self._transport_open = False
        self._outstanding = 0
        self._inflight: list[TelemetryObservation] = []
        self._persisted = 0
        self.fatal_health: StorageHealth | None = None

    @property
    def pending_count(self) -> int:
        return self._outstanding

    @property
    def progress(self) -> TelemetryProgress:
        return TelemetryProgress(
            received_count=self._sequence,
            connection_count=self._epoch,
            unknown_packet_count=self._unknown,
            gap_count=self._gaps,
            last_observed_sequence=self._sequence or None,
            last_observed_day=self._last_day,
        )

    def start(self) -> None:
        if self._writer is not None or self._closing:
            raise RuntimeError("telemetry processor already started or closed")
        self._writer = asyncio.create_task(self._write_loop(), name="telemetry-writer")

    def _fatal(self, code: StorageHealthCode) -> None:
        if self.fatal_health is None:
            self.fatal_health = StorageHealth(
                code, self._sequence, self._persisted, self._outstanding
            )
            self._health_ready.set()
            self._wake.set()

    async def wait_fatal(self) -> StorageHealth:
        await self._health_ready.wait()
        assert self.fatal_health is not None
        return self.fatal_health

    def _append(self, payload: ObservationPayload, *, company_id: int | None = None) -> None:
        if self._outstanding >= self.CAPACITY:
            self._fatal(StorageHealthCode.OVERLOADED)
            assert self.fatal_health is not None
            raise TelemetryPipelineFailed(self.fatal_health)
        sequence = self._sequence + 1
        day, context, quality = None, None, DateQuality.UNKNOWN
        if isinstance(payload, GameDateObservation):
            day, quality = payload.game_day, DateQuality.PACKET_DATE
        elif not isinstance(payload, TelemetryDiagnostic) and self._date is not None:
            day, context = self._date
            quality = DateQuality.PRECEDING_DATE
        item = TelemetryObservation(
            experiment_run_id=self.run_id,
            sequence=sequence,
            connection_epoch=self._epoch,
            received_at=self.utc_now(),
            schema_version=1,
            source=ObservationSource.LIVE_RUNTIME
            if isinstance(payload, TelemetryDiagnostic)
            else ObservationSource.OPENTTD_ADMIN,
            protocol_version=self._protocol,
            kind=_PAYLOAD_KINDS[type(payload)],
            company_id=company_id,
            game_day=day,
            date_context_sequence=context,
            date_quality=quality,
            payload=payload,
        )
        self._sequence = sequence
        self._outstanding += 1
        if isinstance(payload, GameDateObservation):
            self._date = payload.game_day, sequence
            self._last_day = payload.game_day
        self._queue.put_nowait((item, asyncio.get_running_loop().time()))
        self._wake.set()

    def _diagnostic(
        self, code: DiagnosticCode, summary: DiagnosticSummary, *, company_id: int | None = None
    ) -> None:
        self._append(
            TelemetryDiagnostic(
                code=code,
                severity=DiagnosticSeverity.WARNING
                if code
                in {
                    DiagnosticCode.CONNECTION_GAP,
                    DiagnosticCode.PERSISTENCE_RETRY,
                    DiagnosticCode.MISSING_DATE,
                }
                else DiagnosticSeverity.INFO,
                connection_epoch=self._epoch,
                occurred_at=self.utc_now(),
                last_known_day=self._last_day,
                summary=summary,
            ),
            company_id=company_id,
        )

    def emit(self, event: ObserverEvent) -> None:
        if self.fatal_health is not None:
            raise TelemetryPipelineFailed(self.fatal_health)
        if self._writer is None or self._closing:
            raise RuntimeError("telemetry processor is not accepting observations")
        if isinstance(event, ObserverMeasurement):
            if self._protocol is None or not self._transport_open:
                raise ValueError("measurement requires authenticated transport")
            if (
                not isinstance(event.payload, GameDateObservation)
                and self._date is None
                and not self._missing_reported
            ):
                self._diagnostic(DiagnosticCode.MISSING_DATE, DiagnosticSummary.MISSING_DATE)
                self._missing_reported = True
            self._append(event.payload, company_id=getattr(event.payload, "company_id", None))
        elif isinstance(event, ObserverUnknownPacket):
            self._unknown += 1
            self._diagnostic(
                DiagnosticCode.UNKNOWN_PACKET, DiagnosticSummary.UNKNOWN_PACKET_IGNORED
            )
        elif isinstance(event, ObserverCompanyLifecycle):
            code, summary = {
                CompanyLifecycleKind.NEW: (
                    DiagnosticCode.COMPANY_NEW,
                    DiagnosticSummary.COMPANY_CREATED,
                ),
                CompanyLifecycleKind.UPDATE: (
                    DiagnosticCode.COMPANY_UPDATE,
                    DiagnosticSummary.COMPANY_CHANGED,
                ),
                CompanyLifecycleKind.REMOVE: (
                    DiagnosticCode.COMPANY_REMOVE,
                    DiagnosticSummary.COMPANY_REMOVED,
                ),
            }[event.kind]
            self._diagnostic(code, summary, company_id=event.company_id)
        elif isinstance(event, ObserverHealth):
            if event.state is ObserverState.CONNECTING:
                self._date = None
                self._protocol = None
                self._missing_reported = False
            elif event.state is ObserverState.CONNECTED:
                self._epoch += 1
                self._transport_open = True
                self._date = None
                self._protocol = None
                self._missing_reported = False
                self._diagnostic(
                    DiagnosticCode.CONNECTION_OPENED, DiagnosticSummary.CONNECTION_OPENED
                )
            elif event.state is ObserverState.AUTHENTICATED:
                if not self._transport_open:
                    raise ValueError("authentication requires connected transport")
                self._protocol = 2
            elif event.state in {
                ObserverState.CONNECTION_LOST,
                ObserverState.EOF,
                ObserverState.HEARTBEAT_FAILURE,
            }:
                if self._transport_open:
                    self._gaps += 1
                    self._diagnostic(
                        DiagnosticCode.CONNECTION_GAP, DiagnosticSummary.CONNECTION_GAP
                    )
                self._transport_open = False
                self._date = None
                self._protocol = None
            elif event.state in {ObserverState.SERVER_SHUTDOWN, ObserverState.WORLD_RESET}:
                code, summary = (
                    (DiagnosticCode.SERVER_SHUTDOWN, DiagnosticSummary.SERVER_SHUTDOWN)
                    if event.state is ObserverState.SERVER_SHUTDOWN
                    else (DiagnosticCode.WORLD_RESET, DiagnosticSummary.WORLD_RESET)
                )
                self._diagnostic(code, summary)
                self._date = None
            elif event.state in {ObserverState.MALFORMED_PACKET, ObserverState.PROTOCOL_REJECTED}:
                self._diagnostic(DiagnosticCode.PROTOCOL_ERROR, DiagnosticSummary.PROTOCOL_ERROR)

    async def _persist(self, batch: TelemetryBatch) -> bool:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.retry_budget
        retry = 0
        while True:
            try:
                attempt_deadline = min(deadline, loop.time() + 2.0)
                async with asyncio.timeout_at(attempt_deadline):
                    await self.repository.write_batch(batch, deadline=attempt_deadline)
                return True
            except TransientStorageError, TimeoutError:
                if retry == 0 and any(
                    item.kind is not ObservationKind.DIAGNOSTIC for item in batch.observations
                ):
                    try:
                        self._diagnostic(
                            DiagnosticCode.PERSISTENCE_RETRY, DiagnosticSummary.PERSISTENCE_RETRY
                        )
                    except TelemetryPipelineFailed:
                        pass  # The separate fatal channel remains available at full capacity.
                remaining = deadline - loop.time()
                if remaining <= 0:
                    self._fatal(StorageHealthCode.RETRY_EXHAUSTED)
                    return False
                await asyncio.sleep(min(0.25 * 2 ** min(retry, 3), remaining))
                retry += 1
                if loop.time() >= deadline:
                    self._fatal(StorageHealthCode.RETRY_EXHAUSTED)
                    return False
            except TelemetryStorageError, ValueError:
                self._fatal(StorageHealthCode.PERMANENT_FAILURE)
                return False

    async def _write_loop(self) -> None:
        try:
            while not self._closing or self._outstanding:
                if self._queue.empty():
                    self._wake.clear()
                    await self._wake.wait()
                    continue
                first, received = self._queue.get_nowait()
                items = self._inflight
                items.append(first)
                due = received + self.FLUSH_SECONDS
                while len(items) < self.BATCH_SIZE:
                    while not self._queue.empty() and len(items) < self.BATCH_SIZE:
                        items.append(self._queue.get_nowait()[0])
                    if (
                        len(items) == self.BATCH_SIZE
                        or self._closing
                        or self.fatal_health is not None
                    ):
                        break
                    self._wake.clear()
                    try:
                        async with asyncio.timeout_at(due):
                            await self._wake.wait()
                    except TimeoutError:
                        break
                batch = TelemetryBatch(tuple(items), self.progress)
                if not await self._persist(batch):
                    return
                self._outstanding -= len(items)
                self._persisted += len(items)
                items.clear()
        except asyncio.CancelledError:
            self._fatal(StorageHealthCode.CANCELLED)
            raise
        except Exception:
            self._fatal(StorageHealthCode.PERMANENT_FAILURE)

    async def close(self) -> None:
        self._closing = True
        self._wake.set()
        try:
            if self._writer is not None:
                try:
                    async with asyncio.timeout(self.flush_timeout):
                        await asyncio.shield(self._writer)
                except TimeoutError:
                    self._fatal(StorageHealthCode.FLUSH_TIMEOUT)
                    self._writer.cancel()
                    await asyncio.gather(self._writer, return_exceptions=True)
                except asyncio.CancelledError:
                    self._fatal(StorageHealthCode.CANCELLED)
                    self._writer.cancel()
                    await asyncio.gather(self._writer, return_exceptions=True)
                    raise
        finally:
            await self.repository.close()
        if self.fatal_health is not None:
            raise TelemetryPipelineFailed(self.fatal_health)
