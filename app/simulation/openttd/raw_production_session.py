"""Same-run NON-ATOMIC structural + complete raw production; never planner ready."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from app.simulation.openttd.gamescript_protocol import BridgeProtocolError
from app.simulation.openttd.industry_production import (
    IndustryProductionExchange,
    IndustryProductionRequest,
)
from app.simulation.openttd.industry_production_evidence import IndustryProductionEvidence
from app.simulation.openttd.production_observation import (
    EconomyMonth,
    IndustryProductionObservation,
    ProductionBudget,
    ProductionWindowQualification,
)
from app.simulation.openttd.production_session import (
    IndustryProductionSession,
    ProductionConnection,
    ProductionDecisionBoundary,
    ProductionTransport,
)
from app.simulation.openttd.structural_world import (
    StructuralWorldContext,
    StructuralWorldObservation,
)
from app.simulation.openttd.structural_world_session import (
    CapabilityEvidence,
    CatalogEvidence,
    InventoryEvidence,
    StructuralWorldSession,
    StructuralWorldTransport,
)

# These are abstract query allowances, NOT a native total-post-auth-frame contract.
MAX_COMBINED_REQUESTS = 96 + 512
MAX_COMBINED_RESPONSE_BYTES = 49152 + 171520
MAX_PRODUCTION_QUERY_OPERATIONS = 512 * 8
MAX_COMBINED_QUERY_OPERATIONS = 1024 + MAX_PRODUCTION_QUERY_OPERATIONS
PRODUCTION_QUERY_ALLOWANCE = 8


class RawProductionTransport(StructuralWorldTransport, ProductionTransport, Protocol):
    """One authenticated owner supplies the same session and context for all phases."""

    @property
    def session(self) -> ProductionConnection: ...


@dataclass(frozen=True)
class RawProductionBudget:
    max_requests: int = MAX_COMBINED_REQUESTS
    max_response_bytes: int = MAX_COMBINED_RESPONSE_BYTES
    max_operations: int = MAX_COMBINED_QUERY_OPERATIONS

    def __post_init__(self):
        for value, ceiling in (
            (self.max_requests, MAX_COMBINED_REQUESTS),
            (self.max_response_bytes, MAX_COMBINED_RESPONSE_BYTES),
            (self.max_operations, MAX_COMBINED_QUERY_OPERATIONS),
        ):
            if type(value) is not int or not 1 <= value <= ceiling:
                raise ValueError("invalid combined raw-production budget")


@dataclass(frozen=True)
class RawProductionSessionEvidence:
    events: tuple[str, ...]
    accounting: tuple[tuple[int, int, int], ...]
    request_attempts: int
    total_response_bytes: int
    protocol_operations: int
    complete: bool
    failure: str | None
    cleanup_failure: str | None
    retries: int = 0
    reconnects: int = 0
    qualified_for_planning: bool = False


class _ContinuousTransport:
    """A single monotonic abstract ledger wraps every query, including structural ones."""

    def __init__(self, owner, transport):
        self.owner, self.transport = owner, transport

    @property
    def session(self):
        return self.transport.session

    @property
    def context(self):
        return self.transport.context

    async def _query(self, phase, send, operation_budget):
        owner = self.owner
        owner.check(self.transport)
        if owner.phase != phase:
            raise BridgeProtocolError("query outside combined phase barrier")
        remaining = owner.budget.max_operations - owner._operations
        if owner._attempts >= owner.budget.max_requests or remaining < 4:
            raise BridgeProtocolError("combined query budget exhausted before send")
        if owner._bytes >= owner.budget.max_response_bytes:
            raise BridgeProtocolError("combined response budget exhausted before send")
        allowance = PRODUCTION_QUERY_ALLOWANCE if phase == "PRODUCTION" else 16
        owner._attempts += 1
        limit = min(remaining, allowance, operation_budget or remaining)
        exchange = await send(limit)
        owner._bytes += len(exchange.response_payload)
        owner._operations += exchange.protocol_operations
        owner._accounting.append((owner._attempts, owner._bytes, owner._operations))
        if exchange.protocol_operations > limit:
            raise BridgeProtocolError("per-query operation allowance exceeded")
        owner.check(self.transport)
        return exchange

    async def industry_page(self, request, world, *, timeout=5.0, operation_budget=None):
        return await self._query(
            "INVENTORY",
            lambda limit: self.transport.industry_page(
                request, world, timeout=timeout, operation_budget=limit
            ),
            operation_budget,
        )

    async def industry_cargo(self, request, *, timeout, operation_budget=None):
        return await self._query(
            "CAPABILITY",
            lambda limit: self.transport.industry_cargo(
                request, timeout=timeout, operation_budget=limit
            ),
            operation_budget,
        )

    async def cargo_page(self, request, *, timeout, operation_budget=None):
        return await self._query(
            "CATALOG",
            lambda limit: self.transport.cargo_page(
                request, timeout=timeout, operation_budget=limit
            ),
            operation_budget,
        )

    async def industry_production(self, request, *, timeout, operation_budget=None):
        return await self._query(
            "PRODUCTION",
            lambda limit: self.transport.industry_production(
                request, timeout=timeout, operation_budget=limit
            ),
            operation_budget,
        )


class CompleteRawProductionSession:
    """Single-use PRE-DECISION collector; returns two separate immutable observations.

    EconomyMonth is an owner-supplied reading, not a wait or a guessed calendar.
    Failed collection retains evidence and any completed structural observation,
    but never publishes a complete combined result. No historical source is accepted.
    Runtime ownership, native frame accounting and final cleanup remain with the owner.
    """

    def __init__(
        self,
        context: StructuralWorldContext,
        month: EconomyMonth,
        *,
        session_id: str = "openttd15-raw-production-001",
        budget: RawProductionBudget = RawProductionBudget(),
        timeout: float = 5.0,
        decision: ProductionDecisionBoundary | None = None,
        phase_started: Callable[[str], None] | None = None,
        targets_finalized: Callable[[tuple[tuple[int, int], ...]], None] | None = None,
    ):
        if not isinstance(month, EconomyMonth) or not isinstance(budget, RawProductionBudget):
            raise ValueError("typed initial economy month and combined budget required")
        self.context, self.month, self.budget, self.timeout = context, month, budget, timeout
        self.decision = decision if decision is not None else ProductionDecisionBoundary()
        self._phase_started = phase_started
        self._targets_finalized = targets_finalized
        self.phase = "PREPARED"
        self.structural_session = StructuralWorldSession(
            context, session_id=session_id, timeout=timeout, phase_started=self._start_phase
        )
        self.production_session: IndustryProductionSession | None = None
        self.structural: StructuralWorldObservation | None = None
        self.production: IndustryProductionObservation | None = None
        self._started = False
        self._attempts = self._bytes = self._operations = 0
        self._events: list[str] = []
        self._accounting: list[tuple[int, int, int]] = []
        self._failure: str | None = None
        self._cleanup_failure: str | None = None

    def _start_phase(self, phase):
        self.phase = phase
        self._events.append(phase + "_PHASE_STARTED")
        if self._phase_started is not None:
            self._phase_started(phase)

    def check(self, transport):
        self.decision.require_pre_decision()
        self.context.require_same_run(transport.context)
        if transport.session is not self.context.connection_identity:
            raise BridgeProtocolError("combined connection replaced; no reconnect/resume")
        if (
            self._attempts > self.budget.max_requests
            or self._bytes > self.budget.max_response_bytes
            or self._operations > self.budget.max_operations
        ):
            raise BridgeProtocolError("combined raw-production budget exhausted")

    @property
    def evidence(self):
        return RawProductionSessionEvidence(
            tuple(self._events),
            tuple(self._accounting),
            self._attempts,
            self._bytes,
            self._operations,
            self.phase == "COMPLETED",
            self._failure,
            self._cleanup_failure,
        )

    async def collect(
        self,
        transport: RawProductionTransport,
        inventory_evidence: InventoryEvidence,
        capability_evidence: CapabilityEvidence,
        catalog_evidence: CatalogEvidence,
        production_evidence: Callable[
            [IndustryProductionRequest, IndustryProductionExchange],
            Awaitable[IndustryProductionEvidence],
        ],
    ) -> tuple[StructuralWorldObservation, IndustryProductionObservation]:
        if self._started:
            raise BridgeProtocolError("combined session single-use; no retry/resume")
        self._started = True
        self._events.append("COMBINED_SESSION_STARTED")
        production_collecting = False
        connection = transport.session
        try:
            self.check(transport)
            bounded = _ContinuousTransport(self, transport)
            self.structural = await self.structural_session.collect(
                bounded, inventory_evidence, capability_evidence, catalog_evidence
            )
            self.check(transport)
            self._events.append("STRUCTURAL_WORLD_VERIFIED")
            if not self.structural.complete:
                raise BridgeProtocolError("complete structural phase required before production")
            self.structural.structural_world_digest
            self._start_phase("PRODUCTION")
            self._events.append("RAW_PRODUCTION_PHASE_STARTED")
            initial = ProductionWindowQualification.initial(self.structural, self.month)
            self.production_session = IndustryProductionSession(
                bounded,
                self.structural,
                self.context,
                initial,
                session_id=self.structural_session.session_id + "-prod",
                budget=ProductionBudget(max_operations=MAX_PRODUCTION_QUERY_OPERATIONS),
                timeout=self.timeout,
                decision=self.decision,
                context_provider=lambda: transport.context,
            )
            self._events.append("PRODUCTION_TARGET_SET_FINALIZED")
            if self._targets_finalized is not None:
                self._targets_finalized(self.production_session.targets)
            production_collecting = True
            production = await self.production_session.collect(production_evidence)
            production_collecting = False
            self.check(transport)
            if production.qualified_for_planning or production.qualification.rollover_count:
                raise BridgeProtocolError("raw coverage cannot qualify planning history")
            if (
                self._attempts != self.structural.total_requests + len(production.records)
                or self._bytes
                != self.structural.total_response_bytes + production.total_response_bytes
                or self._operations
                != self.structural.protocol_operations + production.protocol_operations
            ):
                raise BridgeProtocolError("continuous phase accounting mismatch")
            self._events.extend(
                (
                    "COMPLETE_PRODUCTION_COVERAGE_VALIDATED",
                    "RAW_PRODUCTION_OBSERVATION_ASSEMBLED",
                    "INDUSTRY_PRODUCTION_OBSERVATION_ASSEMBLED",
                    "PRODUCTION_QUALIFICATION_EVALUATED",
                    "COMBINED_OBSERVATION_VERIFIED",
                    "COMBINED_SESSION_COMPLETED",
                )
            )
            self.production = production
            self.phase = "COMPLETED"
            return self.structural, production
        except BaseException as error:
            self.production = None
            self.phase = "FAILED"
            self._failure = str(error) or type(error).__name__
            self._events.append("COMBINED_SESSION_FAILED")
            if not production_collecting:
                try:
                    async with asyncio.timeout(self.timeout):
                        await connection.close()
                except BaseException as cleanup_error:
                    self._cleanup_failure = str(cleanup_error) or type(cleanup_error).__name__
            elif self.production_session is not None:
                self._cleanup_failure = self.production_session.evidence.cleanup_failure
            raise
