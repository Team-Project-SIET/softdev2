"""Async-only PostgreSQL telemetry transactions; no experiment-session sharing."""

import asyncio
import math
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC
from typing import Annotated, TypeVar

import psycopg
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.experiments.model import LiveTelemetrySessionRecord, TelemetryObservationRecord
from app.simulation.openttd.telemetry import ObservationKind, TelemetryObservation


class TelemetryStorageError(RuntimeError):
    """Finite messages only; never expose SQL, connection strings or driver errors."""


class TransientStorageError(TelemetryStorageError):
    def __init__(self) -> None:
        super().__init__("telemetry storage temporarily unavailable")


class TelemetryIntegrityError(TelemetryStorageError):
    def __init__(self) -> None:
        super().__init__("conflicting telemetry sequence")


class PermanentStorageError(TelemetryStorageError):
    def __init__(self) -> None:
        super().__init__("invalid telemetry storage operation")


Count = Annotated[int, Field(strict=True, ge=0)]


class TelemetryProgress(BaseModel):
    """Absolute receive-side counters, safe to replay after an ambiguous commit."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    received_count: Count
    connection_count: Count = 0
    unknown_packet_count: Count = 0
    gap_count: Count = 0
    dropped_count: Count = 0
    last_observed_sequence: Annotated[int, Field(strict=True, gt=0)] | None = None
    last_observed_day: Annotated[int, Field(strict=True, ge=366)] | None = None


@dataclass(frozen=True)
class TelemetryBatch:
    observations: tuple[TelemetryObservation, ...]
    progress: TelemetryProgress

    def __post_init__(self) -> None:
        if not isinstance(self.observations, tuple) or not 1 <= len(self.observations) <= 100:
            raise ValueError("telemetry batch must contain 1–100 observations")
        for observation in self.observations:
            TelemetryObservation.model_validate(observation.model_dump())
        ids = {item.experiment_run_id for item in self.observations}
        sequences = [item.sequence for item in self.observations]
        if len(ids) != 1 or sequences != sorted(set(sequences)):
            raise ValueError("telemetry batch must be ordered within one run")
        if (
            self.progress.last_observed_sequence is None
            or self.progress.last_observed_sequence < sequences[-1]
            or self.progress.received_count < self.progress.last_observed_sequence
        ):
            raise ValueError("receive counters cannot precede batch")


@dataclass
class _ConnectionScope:
    connection: psycopg.AsyncConnection | None = None
    finished: asyncio.Event = field(default_factory=asyncio.Event)


_scope: ContextVar[_ConnectionScope | None] = ContextVar("telemetry_connection", default=None)


def create_telemetry_engine(url: str | URL | None = None) -> AsyncEngine:
    """Use the existing URL and driver, with no pooled connections or SQL logging."""
    parsed = make_url(str(get_settings().database_url) if url is None else url)
    if parsed.drivername not in {"postgresql", "postgresql+psycopg", "postgresql+psycopg_async"}:
        raise ValueError("telemetry requires PostgreSQL with Psycopg 3")
    parsed = parsed.set(drivername="postgresql+psycopg")

    async def connect() -> psycopg.AsyncConnection:
        args, kwargs = engine.sync_engine.dialect.create_connect_args(parsed)
        connection = await psycopg.AsyncConnection.connect(*args, **kwargs)
        # Capture before SQLAlchemy's first-connect queries, so cancellation can
        # close the socket even while dialect initialization is awaiting a reply.
        scope = _scope.get()
        if scope is not None:
            scope.connection = connection
        return connection

    engine = create_async_engine(parsed, async_creator=connect, poolclass=NullPool, echo=False)
    return engine


def _values(observation: TelemetryObservation) -> dict:
    values = observation.model_dump(mode="python")
    values["payload"] = observation.payload.model_dump(mode="json")
    return values


def _observation(row: TelemetryObservationRecord) -> TelemetryObservation:
    values = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    values["received_at"] = values["received_at"].astimezone(UTC)
    return TelemetryObservation.model_validate(values)


T = TypeVar("T")


class TelemetryRepository:
    """Own async resources only. A T02 live-session row must already exist."""

    def __init__(self, url: str | URL | None = None) -> None:
        if url is not None and not isinstance(url, (str, URL)):
            raise ValueError("telemetry repository owns its deadline-aware engine")
        self.engine = create_telemetry_engine(url)
        self._active: dict[asyncio.Task, _ConnectionScope] = {}
        self._closed = False

    async def _io(self, work: Callable[[AsyncSession], Awaitable[T]], deadline: float) -> T:
        if self._closed:
            raise PermanentStorageError()
        if not math.isfinite(deadline):
            raise ValueError("telemetry requires a finite I/O deadline")
        loop = asyncio.get_running_loop()
        if deadline <= loop.time():
            raise TransientStorageError()
        session = AsyncSession(self.engine, expire_on_commit=False)
        scope = _ConnectionScope()

        async def transaction() -> T:
            await session.connection()
            remaining_ms = max(1, int((deadline - loop.time()) * 900))
            await session.execute(
                text("SELECT set_config('statement_timeout', :milliseconds, true)"),
                {"milliseconds": str(remaining_ms)},
            )
            value = await work(session)
            await session.commit()
            return value

        token = _scope.set(scope)
        task = asyncio.create_task(transaction())
        self._active[task] = scope
        try:
            # Shield only so the deadline handler can close the driver socket
            # before cancellation. Psycopg otherwise attempts server cancellation
            # with its own timeout, potentially extending this operation's budget.
            async with asyncio.timeout_at(deadline):
                return await asyncio.shield(task)
        except BaseException as exc:
            if scope.connection is not None:
                # NullPool Psycopg AsyncConnection.close performs PQfinish; it
                # does not wait for a server reply or issue a network rollback.
                await scope.connection.close()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await session.invalidate()
            if isinstance(exc, asyncio.CancelledError):
                raise
            if isinstance(exc, TelemetryStorageError):
                raise
            if isinstance(exc, TimeoutError):
                raise TransientStorageError() from None
            if isinstance(exc, IntegrityError):
                raise PermanentStorageError() from None
            if isinstance(exc, DBAPIError):
                state = getattr(exc.orig, "sqlstate", None)
                if (
                    exc.connection_invalidated
                    or state is None
                    or state[:2] in {"08", "40", "53", "57"}
                ):
                    raise TransientStorageError() from None
            if isinstance(exc, SQLAlchemyError):
                raise PermanentStorageError() from None
            raise
        finally:
            try:
                await session.close()
            finally:
                self._active.pop(task, None)
                _scope.reset(token)
                scope.finished.set()

    @staticmethod
    async def _locked_session(session: AsyncSession, run_id: int) -> LiveTelemetrySessionRecord:
        row = await session.scalar(
            select(LiveTelemetrySessionRecord)
            .where(LiveTelemetrySessionRecord.experiment_run_id == run_id)
            .with_for_update()
        )
        if row is None:
            raise PermanentStorageError()
        return row

    @staticmethod
    def _update_progress(row: LiveTelemetrySessionRecord, progress: TelemetryProgress) -> None:
        for name in (
            "received_count",
            "connection_count",
            "unknown_packet_count",
            "gap_count",
            "dropped_count",
        ):
            setattr(row, name, max(getattr(row, name), getattr(progress, name)))
        if (progress.last_observed_sequence or 0) >= (row.last_observed_sequence or 0):
            row.last_observed_sequence = progress.last_observed_sequence
            row.last_observed_day = progress.last_observed_day
        if row.telemetry_status == "pending":
            row.telemetry_status = "recording"

    async def write_batch(self, batch: TelemetryBatch, *, deadline: float) -> None:
        async def write(session: AsyncSession) -> None:
            observations = batch.observations
            run_id = observations[0].experiment_run_id
            summary = await self._locked_session(session, run_id)
            inserted = tuple(
                (
                    await session.scalars(
                        insert(TelemetryObservationRecord)
                        .values([_values(item) for item in observations])
                        .on_conflict_do_nothing()
                        .returning(TelemetryObservationRecord.sequence)
                    )
                ).all()
            )
            rows = (
                await session.scalars(
                    select(TelemetryObservationRecord)
                    .where(
                        TelemetryObservationRecord.experiment_run_id == run_id,
                        TelemetryObservationRecord.sequence.in_(
                            [item.sequence for item in observations]
                        ),
                    )
                    .order_by(TelemetryObservationRecord.sequence)
                )
            ).all()
            if tuple(_observation(row) for row in rows) != observations:
                raise TelemetryIntegrityError()
            summary.persisted_count += len(inserted)
            summary.final_persisted_sequence = max(
                summary.final_persisted_sequence or 0, observations[-1].sequence
            )
            self._update_progress(summary, batch.progress)
            for item in observations:
                if item.protocol_version is not None:
                    summary.protocol_version = item.protocol_version
                if item.connection_epoch > 0 and summary.connected_at is None:
                    summary.connected_at = item.received_at

        await self._io(write, deadline)

    async def read(
        self,
        run_id: int,
        *,
        after_sequence: int = 0,
        limit: int = 100,
        kind: str | None = None,
        company_id: int | None = None,
        deadline: float,
    ) -> tuple[TelemetryObservation, ...]:
        if (
            type(run_id) is not int
            or run_id <= 0
            or type(after_sequence) is not int
            or after_sequence < 0
            or type(limit) is not int
            or not 1 <= limit <= 1000
            or (kind is not None and kind not in tuple(ObservationKind))
            or (
                company_id is not None
                and (type(company_id) is not int or not 0 <= company_id <= 14)
            )
        ):
            raise ValueError("invalid telemetry cursor")

        async def read_rows(session: AsyncSession) -> tuple[TelemetryObservation, ...]:
            statement = (
                select(TelemetryObservationRecord)
                .where(
                    TelemetryObservationRecord.experiment_run_id == run_id,
                    TelemetryObservationRecord.sequence > after_sequence,
                )
                .order_by(TelemetryObservationRecord.sequence)
                .limit(limit)
            )
            if kind is not None:
                statement = statement.where(TelemetryObservationRecord.kind == kind)
            if company_id is not None:
                statement = statement.where(TelemetryObservationRecord.company_id == company_id)
            return tuple(_observation(row) for row in (await session.scalars(statement)).all())

        return await self._io(read_rows, deadline)

    async def summary(self, run_id: int, *, deadline: float) -> dict:
        async def read_summary(session: AsyncSession) -> dict:
            row = await session.get(LiveTelemetrySessionRecord, run_id)
            if row is None:
                raise PermanentStorageError()
            return {column.name: getattr(row, column.name) for column in row.__table__.columns}

        return await self._io(read_summary, deadline)

    async def close(self) -> None:
        self._closed = True
        active = tuple(self._active.items())
        for task, scope in active:
            if scope.connection is not None:
                await scope.connection.close()
            task.cancel()
        if active:
            await asyncio.gather(*(task for task, _ in active), return_exceptions=True)
            await asyncio.gather(*(scope.finished.wait() for _, scope in active))
        await self.engine.dispose()
