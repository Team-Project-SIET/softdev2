"""Bounded same-run PRE-DECISION collection; no runtime launches, retries or P08."""

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from app.simulation.openttd.gamescript_protocol import BridgeProtocolError, validate_request_id
from app.simulation.openttd.industry_production import (
    IndustryProductionExchange,
    IndustryProductionRequest,
)
from app.simulation.openttd.industry_production_evidence import (
    IndustryProductionEvidence,
    ProductionTransaction,
)
from app.simulation.openttd.production_observation import (
    IndustryProductionObservation,
    ProductionBudget,
    ProductionWindowQualification,
    production_pairs,
)
from app.simulation.openttd.structural_world import (
    StructuralWorldContext,
    StructuralWorldObservation,
)


class ProductionConnection(Protocol):
    async def close(self) -> None: ...


class ProductionTransport(Protocol):
    @property
    def session(self) -> ProductionConnection: ...

    async def industry_production(
        self,
        request: IndustryProductionRequest,
        *,
        timeout: float,
        operation_budget: int | None = None,
    ) -> IndustryProductionExchange: ...


class DecisionStage(Enum):
    PRE_DECISION = "pre_decision"
    POST_DECISION = "post_decision"


@dataclass
class ProductionDecisionBoundary:
    """Owner marks optimizer intervention; a production collector never consumes evaluation data."""

    stage: DecisionStage = DecisionStage.PRE_DECISION

    def mark_decision(self) -> None:
        self.stage = DecisionStage.POST_DECISION

    def require_pre_decision(self) -> None:
        if self.stage is not DecisionStage.PRE_DECISION:
            raise BridgeProtocolError("post-decision telemetry cannot enter production input")


@dataclass(frozen=True)
class ProductionSessionEvidence:
    events: tuple[str, ...]
    transactions: tuple[ProductionTransaction, ...]
    exchanges: tuple[IndustryProductionExchange, ...]
    request_attempts: int
    total_response_bytes: int
    protocol_operations: int
    failure: str | None
    cleanup_failure: str | None
    complete: bool
    retries: int = 0
    reconnects: int = 0


class IndustryProductionSession:
    def __init__(
        self,
        transport: ProductionTransport,
        source: StructuralWorldObservation,
        context: StructuralWorldContext,
        qualification: ProductionWindowQualification,
        *,
        session_id: str = "openttd15-industry-production-001",
        budget: ProductionBudget = ProductionBudget(),
        timeout: float = 5.0,
        decision: ProductionDecisionBoundary | None = None,
        context_provider: Callable[[], StructuralWorldContext] | None = None,
    ):
        validate_request_id(session_id + "-p512")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("finite positive production timeout required")
        source.inventory.context.require_same_run(context)
        context.require_same_run(qualification.context)
        if source.structural_world_digest != qualification.source_structural_world_digest:
            raise BridgeProtocolError("production structural provenance mismatch")
        self.transport, self.source, self.context, self.qualification = (
            transport,
            source,
            context,
            qualification,
        )
        self._connection = transport.session
        self._targets = production_pairs(source)
        self.session_id, self.budget, self.timeout = session_id, budget, timeout
        self.decision = decision if decision is not None else ProductionDecisionBoundary()
        self.context_provider = context_provider or (lambda: context)
        self._transactions: list[ProductionTransaction] = []
        self._exchanges: list[IndustryProductionExchange] = []
        self._events: list[str] = []
        self._attempts = self._bytes = self._operations = 0
        self._started = False
        self._failure: str | None = None
        self._cleanup_failure: str | None = None
        self.observation: IndustryProductionObservation | None = None
        self._require_context()

    @property
    def targets(self):
        return self._targets

    def _require_context(self) -> None:
        self.decision.require_pre_decision()
        self.context.require_same_run(self.context_provider())
        if self.transport.session is not self.context.connection_identity:
            raise BridgeProtocolError("production connection replaced")

    @property
    def evidence(self) -> ProductionSessionEvidence:
        return ProductionSessionEvidence(
            tuple(self._events),
            tuple(self._transactions),
            tuple(self._exchanges),
            self._attempts,
            self._bytes,
            self._operations,
            self._failure,
            self._cleanup_failure,
            self.observation is not None,
        )

    async def collect(
        self,
        evidence_for: Callable[
            [IndustryProductionRequest, IndustryProductionExchange],
            Awaitable[IndustryProductionEvidence],
        ],
    ) -> IndustryProductionObservation:
        """Await canonical GS liveness evidence from evidence_for(request, exchange)."""
        if self._started:
            raise BridgeProtocolError("production session cannot retry/resume")
        self._started = True
        self._events.extend(
            (
                "INDUSTRY_PRODUCTION_SESSION_STARTED",
                "INDUSTRY_PRODUCTION_PHASE_STARTED",
                "TARGET_SET_FINALIZED",
            )
        )
        try:
            for number, (industry_id, cargo_id) in enumerate(self.targets, 1):
                self._require_context()
                self.budget.require(self._attempts + 1, self._bytes, self._operations + 4)
                request = IndustryProductionRequest(
                    f"{self.session_id}-p{number:03d}", industry_id, cargo_id
                )
                self._attempts += 1
                exchange = await self.transport.industry_production(
                    request,
                    timeout=self.timeout,
                    operation_budget=self.budget.max_operations - self._operations,
                )
                self._exchanges.append(exchange)
                self._bytes += len(exchange.response_payload)
                self._operations += exchange.protocol_operations
                self.budget.require(self._attempts, self._bytes, self._operations)
                self._require_context()
                exchange.validate()
                if (
                    exchange.request_payload != request.to_bytes()
                    or exchange.response.record.pair != (industry_id, cargo_id)
                ):
                    raise BridgeProtocolError("wrong production pair/request")
                if not self.qualification.current_month.contains(exchange.response.record):
                    raise BridgeProtocolError("production read crossed economy window")
                async with asyncio.timeout(self.timeout):
                    gs = await evidence_for(request, exchange)
                transaction = ProductionTransaction(exchange, gs)
                self._transactions.append(transaction)
                transaction.validate()
                self._require_context()
                self._events.append("PRODUCTION_RECORD_VALIDATED")
            self._require_context()
            observation = IndustryProductionObservation(
                self.source,
                self.context,
                self.qualification,
                tuple(t.exchange.response.record for t in self._transactions),
                self._bytes,
                self._operations,
                tuple(self._transactions),
                self.budget,
            )
            self._events.extend(
                (
                    "COMPLETE_PRODUCTION_COVERAGE_VALIDATED",
                    "PRODUCTION_OBSERVATION_ASSEMBLED",
                    "INDUSTRY_PRODUCTION_OBSERVATION_ASSEMBLED",
                    "PRODUCTION_QUALIFICATION_EVALUATED",
                    "INDUSTRY_PRODUCTION_SESSION_COMPLETED",
                )
            )
            self.observation = observation
            return observation
        except BaseException as error:
            self._failure = str(error) or type(error).__name__
            self._events.append("INDUSTRY_PRODUCTION_SESSION_FAILED")
            try:
                async with asyncio.timeout(self.timeout):
                    await self._connection.close()
            except BaseException as cleanup_error:
                self._cleanup_failure = str(cleanup_error) or type(cleanup_error).__name__
            raise
