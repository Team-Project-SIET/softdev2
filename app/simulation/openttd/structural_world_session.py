"""Python-only inventory -> capability -> catalog coordination; no native lifecycle."""

import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from app.simulation.openttd.cargo_catalog import (
    CargoCatalogBudget,
    CargoCatalogObservation,
    CargoCatalogSession,
    CatalogTransport,
    catalog_request_id,
    validate_capability_catalog,
)
from app.simulation.openttd.cargo_page import CargoPageExchange, CargoPageRequest
from app.simulation.openttd.cargo_page_evidence import CargoPageEvidence
from app.simulation.openttd.gamescript_protocol import BridgeProtocolError
from app.simulation.openttd.gamescript_transport import TransportTimeout
from app.simulation.openttd.industry_capability import (
    CargoTransport,
    IndustryCapabilityObservation,
    IndustryCapabilitySession,
    capability_request_id,
)
from app.simulation.openttd.industry_cargo import IndustryCargoExchange, IndustryCargoRequest
from app.simulation.openttd.industry_cargo_evidence import IndustryCargoEvidence
from app.simulation.openttd.industry_inventory import (
    IndustryInventoryObservation,
    inventory_request_id,
)
from app.simulation.openttd.industry_page import IndustryPageExchange, IndustryPageRequest
from app.simulation.openttd.industry_page_evidence import IndustryPageEvidence
from app.simulation.openttd.industry_query import IndustryInventorySession, IndustryPageTransport
from app.simulation.openttd.structural_world import (
    ScopedObservation,
    StructuralWorldBudget,
    StructuralWorldContext,
    StructuralWorldObservation,
)
from app.simulation.openttd.world_info import WorldInfoResponse

STRUCTURAL_WORLD_SESSION_ID = "openttd15-structural-world-001"
STRUCTURAL_PAGE_SIZE = 2
STRUCTURAL_CATALOG_BUDGET = CargoCatalogBudget(32, 64, 16384, 512)
type Phase = Literal[
    "PREPARED", "INVENTORY", "CAPABILITY", "CATALOG", "ASSEMBLY", "COMPLETED", "FAILED"
]
type QueryExchange = IndustryPageExchange | IndustryCargoExchange | CargoPageExchange
type InventoryEvidence = Callable[
    [IndustryPageRequest, IndustryPageExchange], Awaitable[IndustryPageEvidence]
]
type CapabilityEvidence = Callable[
    [IndustryCargoRequest, IndustryCargoExchange], Awaitable[IndustryCargoEvidence]
]
type CatalogEvidence = Callable[[CargoPageRequest, CargoPageExchange], Awaitable[CargoPageEvidence]]


class StructuralWorldTransport(IndustryPageTransport, CargoTransport, CatalogTransport, Protocol):
    """Future runtime owner supplies authenticated context and one continuous session."""

    @property
    def session(self) -> object: ...

    @property
    def context(self) -> StructuralWorldContext: ...


@dataclass(frozen=True)
class StructuralWorldSessionEvidence:
    session_id: str
    events: tuple[str, ...]
    exchanges: tuple[QueryExchange, ...]
    request_attempts: int
    total_response_bytes: int
    protocol_operations: int
    complete: bool
    structural_world_digest: str | None
    failure: str | None
    retries: Literal[0] = 0
    reconnects: Literal[0] = 0


class _BoundedStructuralTransport:
    def __init__(self, transport: StructuralWorldTransport, owner: StructuralWorldSession):
        self.transport, self.owner = transport, owner

    @property
    def session(self) -> object:
        return self.transport.session

    async def _query[T: QueryExchange](
        self, phase: Phase, operation_budget: int | None, send: Callable[[int], Awaitable[T]]
    ) -> T:
        owner = self.owner
        owner.check(self.transport)
        if owner.phase != phase:
            raise BridgeProtocolError("structural query before phase completion barrier")
        remaining = owner.budget.max_operations - owner.evidence.protocol_operations
        if owner.evidence.request_attempts >= owner.budget.max_requests:
            raise BridgeProtocolError("combined request budget exhausted before send")
        if remaining < 4:
            raise BridgeProtocolError("combined Admin frame budget exhausted before send")
        if owner.evidence.total_response_bytes >= owner.budget.max_response_bytes:
            raise BridgeProtocolError("combined byte budget exhausted before send")
        owner._request_attempts += 1
        exchange = await send(min(16, remaining, operation_budget or remaining))
        owner._exchanges.append(exchange)  # Keep received evidence even if later validation fails.
        owner.check(self.transport)
        return exchange

    async def industry_page(
        self,
        request: IndustryPageRequest,
        world: WorldInfoResponse,
        *,
        timeout: float = 5.0,
        operation_budget: int | None = None,
    ) -> IndustryPageExchange:
        return await self._query(
            "INVENTORY",
            operation_budget,
            lambda remaining: self.transport.industry_page(
                request, world, timeout=timeout, operation_budget=remaining
            ),
        )

    async def industry_cargo(
        self,
        request: IndustryCargoRequest,
        *,
        timeout: float,
        operation_budget: int | None = None,
    ) -> IndustryCargoExchange:
        return await self._query(
            "CAPABILITY",
            operation_budget,
            lambda remaining: self.transport.industry_cargo(
                request, timeout=timeout, operation_budget=remaining
            ),
        )

    async def cargo_page(
        self,
        request: CargoPageRequest,
        *,
        timeout: float,
        operation_budget: int | None = None,
    ) -> CargoPageExchange:
        return await self._query(
            "CATALOG",
            operation_budget,
            lambda remaining: self.transport.cargo_page(
                request, timeout=timeout, operation_budget=remaining
            ),
        )


class StructuralWorldSession:
    """One stable owned runtime; no reconnect, resume, launch, or planning adaptation.

    Failed sessions retain completed components and received exchanges, but never a
    complete structural observation. Per-command validators/evidence remain unchanged.
    """

    def __init__(
        self,
        context: StructuralWorldContext,
        *,
        session_id: str = STRUCTURAL_WORLD_SESSION_ID,
        budget: StructuralWorldBudget = StructuralWorldBudget(),
        timeout: float = 5.0,
        phase_started: Callable[[Phase], None] | None = None,
    ):
        if not isinstance(context, StructuralWorldContext) or not isinstance(
            budget, StructuralWorldBudget
        ):
            raise ValueError("typed structural context and budget required")
        inventory_request_id(session_id + "-inv", 32)
        capability_request_id(session_id + "-cap", 63999)
        catalog_request_id(session_id + "-cat", 32)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("positive finite timeout required")
        self.context, self.session_id, self.budget, self.timeout = (
            context,
            session_id,
            budget,
            timeout,
        )
        self.inventory_session = IndustryInventorySession(
            session_id + "-inv", context.world, page_size=STRUCTURAL_PAGE_SIZE, timeout=timeout
        )
        self.capability_session: IndustryCapabilitySession | None = None
        self.catalog_session = CargoCatalogSession(
            session_id + "-cat",
            page_size=STRUCTURAL_PAGE_SIZE,
            budget=STRUCTURAL_CATALOG_BUDGET,
            timeout=timeout,
            runtime_identity=context.world.runtime_identity,
            world_id=context.world.world_id,
        )
        self.inventory: IndustryInventoryObservation | None = None
        self.capability: IndustryCapabilityObservation | None = None
        self.catalog: CargoCatalogObservation | None = None
        self.observation: StructuralWorldObservation | None = None
        self.phase: Phase = "PREPARED"
        self._phase_started = phase_started
        self._started = False
        self._events: list[str] = []
        self._exchanges: list[QueryExchange] = []
        self._request_attempts = 0
        self._failure: str | None = None

    @property
    def evidence(self) -> StructuralWorldSessionEvidence:
        return StructuralWorldSessionEvidence(
            self.session_id,
            tuple(self._events),
            tuple(self._exchanges),
            self._request_attempts,
            sum(len(e.response_payload) for e in self._exchanges),
            sum(e.protocol_operations for e in self._exchanges),
            self.observation is not None,
            self.observation.structural_world_digest if self.observation else None,
            self._failure,
        )

    def check(self, transport: StructuralWorldTransport) -> None:
        self.context.require_same_run(transport.context)
        if transport.session is not self.context.connection_identity:
            raise BridgeProtocolError("structural connection changed; no reconnect/resume")
        evidence = self.evidence
        if (
            evidence.request_attempts > self.budget.max_requests
            or evidence.total_response_bytes > self.budget.max_response_bytes
            or evidence.protocol_operations > self.budget.max_operations
        ):
            raise BridgeProtocolError("combined structural-world budget exhausted")

    def start_phase(self, phase: Phase) -> None:
        self.phase = phase
        if self._phase_started is not None:
            self._phase_started(phase)

    async def collect(
        self,
        transport: StructuralWorldTransport,
        inventory_evidence: InventoryEvidence,
        capability_evidence: CapabilityEvidence,
        catalog_evidence: CatalogEvidence,
    ) -> StructuralWorldObservation:
        if self._started:
            raise BridgeProtocolError("structural-world session single-use; no retry/resume")
        self._started = True
        self._events.append("STRUCTURAL_WORLD_SESSION_STARTED")
        bounded = _BoundedStructuralTransport(transport, self)
        try:
            self.check(transport)

            async def inventory_native(
                q: IndustryPageRequest, e: IndustryPageExchange
            ) -> IndustryPageEvidence:
                self.check(transport)
                native = await inventory_evidence(q, e)
                self.check(transport)
                return native

            async def capability_native(
                q: IndustryCargoRequest, e: IndustryCargoExchange
            ) -> IndustryCargoEvidence:
                self.check(transport)
                native = await capability_evidence(q, e)
                self.check(transport)
                return native

            async def catalog_native(
                q: CargoPageRequest, e: CargoPageExchange
            ) -> CargoPageEvidence:
                self.check(transport)
                native = await catalog_evidence(q, e)
                self.check(transport)
                return native

            self.start_phase("INVENTORY")
            self.inventory = await self.inventory_session.collect(bounded, inventory_native)
            self.check(transport)
            if not self.inventory.complete:
                raise BridgeProtocolError("complete inventory phase required")
            self.inventory.inventory_digest  # Finalize semantic identity before capability starts.
            self._events.append("INDUSTRY_INVENTORY_COMPLETED")
            self.start_phase("CAPABILITY")
            self.capability_session = IndustryCapabilitySession(
                self.session_id + "-cap", self.inventory, timeout=self.timeout
            )
            self.capability = await self.capability_session.collect(bounded, capability_native)
            self.check(transport)
            if not self.capability.complete:
                raise BridgeProtocolError("complete capability phase required")
            self.capability.capability_digest  # Finalize before the catalog phase callback.
            self._events.append("INDUSTRY_CAPABILITY_COMPLETED")
            self.start_phase("CATALOG")
            self.catalog = await self.catalog_session.collect(bounded, catalog_native)
            self.check(transport)
            if not self.catalog.complete:
                raise BridgeProtocolError("complete catalog phase required")
            self.catalog.catalog_digest  # Finalize before structural assembly.
            self._events.append("CARGO_CATALOG_COMPLETED")
            self.start_phase("ASSEMBLY")
            validate_capability_catalog(self.capability, self.catalog)
            result = StructuralWorldObservation(
                ScopedObservation(self.inventory, self.context),
                ScopedObservation(self.capability, self.context),
                ScopedObservation(self.catalog, self.context),
                self.budget,
            )
            self._events.extend(("REFERENTIAL_INTEGRITY_VALIDATED", "STRUCTURAL_WORLD_ASSEMBLED"))
            result.structural_world_digest
            self.check(transport)
            self.observation = result
            self.phase = "COMPLETED"
            self._events.extend(("STRUCTURAL_WORLD_VERIFIED", "STRUCTURAL_WORLD_SESSION_COMPLETED"))
            return result
        except BaseException as error:
            if isinstance(error, TimeoutError):
                error = TransportTimeout("structural-world phase deadline expired")
            self.observation = None
            self.phase = "FAILED"
            self._failure = f"{type(error).__name__}: {error}"
            self._events.append("STRUCTURAL_WORLD_SESSION_FAILED")
            raise error
