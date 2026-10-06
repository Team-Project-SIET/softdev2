"""Bounded Python industry assembly; one continuous transport, no retry or P08 mapping."""

import asyncio
import math
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Protocol

from app.simulation.openttd.gamescript_protocol import BridgeProtocolError
from app.simulation.openttd.gamescript_transport import TransportTimeout
from app.simulation.openttd.industry_inventory import (
    DEFAULT_INDUSTRY_PAGE_SIZE,
    MAX_INDUSTRY_PAGES,
    IndustryInventoryBudget,
    IndustryInventoryObservation,
    IndustryInventoryPage,
    IndustryInventorySessionEvidence,
    IndustryInventoryWorld,
    inventory_request_id,
)
from app.simulation.openttd.industry_page import (
    MAX_PAGE_SIZE,
    IndustryPageExchange,
    IndustryPageRequest,
    IndustryRecord,
)
from app.simulation.openttd.industry_page_evidence import IndustryPageEvidence
from app.simulation.openttd.world_info import WorldInfoResponse


class IndustryPageTransport(Protocol):
    async def industry_page(
        self,
        request: IndustryPageRequest,
        world: WorldInfoResponse,
        *,
        timeout: float = 5.0,
        operation_budget: int | None = None,
    ) -> IndustryPageExchange: ...


async def _walk_pages(
    transport: IndustryPageTransport,
    world: WorldInfoResponse,
    session_id: str,
    page_size: int,
    budget: IndustryInventoryBudget,
    timeout: float,
) -> AsyncIterator[IndustryPageExchange]:
    inventory_request_id(session_id, budget.max_pages)  # Validate every ID before any I/O.
    IndustryPageRequest(inventory_request_id(session_id, 1), None, page_size)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be positive and finite")
    after = last_id = None
    used_ids: set[str] = set()
    cursors: set[int] = set()
    records = response_bytes = operations = 0
    connection = getattr(transport, "session", None)
    for number in range(1, budget.max_pages + 1):
        if getattr(transport, "session", None) is not connection:
            raise BridgeProtocolError("inventory connection changed; no resume")
        if budget.max_operations - operations < 4:
            raise BridgeProtocolError("industry protocol operation budget exhausted")
        request = IndustryPageRequest(inventory_request_id(session_id, number), after, page_size)
        if request.request_id in used_ids:
            raise BridgeProtocolError("repeated inventory request_id")
        used_ids.add(request.request_id)
        try:
            async with asyncio.timeout(timeout):
                exchange = await transport.industry_page(
                    request,
                    world,
                    timeout=timeout,
                    operation_budget=budget.max_operations - operations,
                )
        except TimeoutError as error:
            raise TransportTimeout("inventory page deadline expired") from error
        if getattr(transport, "session", None) is not connection:
            raise BridgeProtocolError("inventory connection changed during request")
        if exchange.request_payload != request.to_bytes():
            raise BridgeProtocolError("pagination transaction/request mismatch")
        exchange.validate(world)
        response = exchange.response
        records += len(response.industries)
        response_bytes += len(exchange.response_payload)
        operations += exchange.protocol_operations
        if records > budget.max_records:
            raise BridgeProtocolError("industry record budget exhausted")
        if response_bytes > budget.max_response_bytes:
            raise BridgeProtocolError("industry cumulative byte budget exhausted")
        if operations > budget.max_operations:
            raise BridgeProtocolError("industry protocol operation budget exhausted")
        for record in response.industries:
            if last_id is not None and record.id <= last_id:
                raise BridgeProtocolError("duplicate/non-ascending industry across pages")
            last_id = record.id
        next_cursor = response.next_after_id
        if response.has_more:
            if (
                next_cursor is None
                or next_cursor in cursors
                or (after is not None and next_cursor <= after)
            ):
                raise BridgeProtocolError("repeated/regressing pagination cursor")
            cursors.add(next_cursor)
        yield exchange
        if not response.has_more:
            return
        after = next_cursor
    raise BridgeProtocolError("industry pagination page budget exhausted")


class IndustryInventorySession:
    """Single-use session. Failed evidence is available; partial observations never return."""

    def __init__(
        self,
        session_id: str,
        world: IndustryInventoryWorld,
        *,
        page_size: int = DEFAULT_INDUSTRY_PAGE_SIZE,
        budget: IndustryInventoryBudget = IndustryInventoryBudget(),
        timeout: float = 5.0,
    ) -> None:
        inventory_request_id(session_id, budget.max_pages)
        IndustryPageRequest(inventory_request_id(session_id, 1), None, page_size)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive and finite")
        self.session_id, self.world = session_id, world
        self.page_size, self.budget, self.timeout = page_size, budget, timeout
        self._pages: list[IndustryInventoryPage] = []
        self._exchanges: list[IndustryPageExchange] = []
        self._events: list[str] = []
        self._started = False
        self._digest: str | None = None
        self._failure: str | None = None

    @property
    def evidence(self) -> IndustryInventorySessionEvidence:
        exchanges = tuple(self._exchanges)
        return IndustryInventorySessionEvidence(
            self.session_id,
            tuple(self._events),
            tuple(e.receipt.request_id for e in exchanges),
            tuple(e.receipt.request_payload_sha256 for e in exchanges),
            tuple(e.receipt.response_payload_sha256 for e in exchanges),
            tuple(IndustryPageRequest.parse(e.request_payload).after_id for e in exchanges),
            tuple(e.response.next_after_id for e in exchanges),
            sum(len(e.response.industries) for e in exchanges),
            sum(len(e.response_payload) for e in exchanges),
            sum(e.protocol_operations for e in exchanges),
            exchanges[-1].response.has_more if exchanges else None,
            self._digest,
            self._failure,
        )

    @property
    def page_exchanges(self) -> tuple[IndustryPageExchange, ...]:
        """Retained network receipts, including a page whose native evidence later failed."""
        return tuple(self._exchanges)

    async def collect(
        self,
        transport: IndustryPageTransport,
        gamescript_evidence: Callable[
            [IndustryPageRequest, IndustryPageExchange], Awaitable[IndustryPageEvidence]
        ],
    ) -> IndustryInventoryObservation:
        if self._started:
            raise BridgeProtocolError("inventory session is single-use; no retry/resume")
        self._started = True
        self._events.append("INVENTORY_SESSION_STARTED")
        connection = getattr(transport, "session", None)
        try:
            async for exchange in _walk_pages(
                transport,
                self.world.dimensions,
                self.session_id,
                self.page_size,
                self.budget,
                self.timeout,
            ):
                request = IndustryPageRequest.parse(exchange.request_payload)
                self._exchanges.append(exchange)
                try:
                    async with asyncio.timeout(self.timeout):
                        native = await gamescript_evidence(request, exchange)
                except TimeoutError as error:
                    raise TransportTimeout(
                        "inventory GameScript evidence deadline expired"
                    ) from error
                if getattr(transport, "session", None) is not connection:
                    raise BridgeProtocolError("inventory connection changed; no resume")
                page = IndustryInventoryPage(exchange, native)
                page.validate(self.world.dimensions)
                self._pages.append(page)
                self._events.append(
                    f"PAGE_{len(self._pages)}_VALIDATED"
                    if exchange.response.has_more
                    else "FINAL_PAGE_VALIDATED"
                )
            result = IndustryInventoryObservation(
                self.session_id, self.world, tuple(self._pages), self.budget
            )
            self._digest = result.inventory_digest
            self._events.extend(("INVENTORY_ASSEMBLED", "INVENTORY_SESSION_COMPLETED"))
            return result
        except BaseException as error:
            self._failure = f"{type(error).__name__}: {error}"
            self._events.append("INVENTORY_SESSION_FAILED")
            raise


async def collect_industries(
    transport: IndustryPageTransport,
    world: WorldInfoResponse,
    *,
    request_prefix: str,
    limit: int = MAX_PAGE_SIZE,
    max_pages: int = MAX_INDUSTRY_PAGES,
    timeout: float = 5.0,
) -> list[IndustryRecord]:
    """Compatibility list collector using the same bounded chain, without native log evidence."""
    result: list[IndustryRecord] = []
    async for exchange in _walk_pages(
        transport,
        world,
        request_prefix,
        limit,
        IndustryInventoryBudget(max_pages=max_pages),
        timeout,
    ):
        result.extend(exchange.response.industries)
    return result
