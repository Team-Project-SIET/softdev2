"""Bounded structural catalog collection and referential validation; no P08 adapter."""

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from app.simulation.openttd.cargo_page import (
    DEFAULT_CARGO_PAGE_SIZE,
    CargoPageExchange,
    CargoPageRequest,
)
from app.simulation.openttd.cargo_page import (
    CargoCatalogRecord as CargoCatalogRecord,
)
from app.simulation.openttd.cargo_page import (
    CargoPageReceipt as CargoPageReceipt,
)
from app.simulation.openttd.cargo_page_evidence import CargoPageEvidence
from app.simulation.openttd.catalog_observation import (
    CargoCatalogBudget as CargoCatalogBudget,
)
from app.simulation.openttd.catalog_observation import (
    CargoCatalogObservation as CargoCatalogObservation,
)
from app.simulation.openttd.catalog_observation import (
    CargoCatalogPage as CargoCatalogPage,
)
from app.simulation.openttd.catalog_observation import (
    catalog_request_id as catalog_request_id,
)
from app.simulation.openttd.catalog_observation import (
    validate_capability_catalog as validate_capability_catalog,
)
from app.simulation.openttd.gamescript_protocol import BridgeProtocolError, validate_request_id
from app.simulation.openttd.gamescript_transport import TransportTimeout
from app.simulation.openttd.runtime.identity import RuntimeIdentity


class CatalogTransport(Protocol):
    async def cargo_page(
        self, request: CargoPageRequest, *, timeout: float, operation_budget: int | None = None
    ) -> CargoPageExchange: ...


@dataclass(frozen=True)
class CargoCatalogSessionEvidence:
    session_id: str
    events: tuple[str, ...]
    exchanges: tuple[CargoPageExchange, ...]
    complete: bool
    catalog_digest: str | None
    failure: str | None


class CargoCatalogSession:
    """Single-use collection in one stable configuration; no reconnect or retry."""

    def __init__(
        self,
        session_id: str,
        *,
        page_size: int = DEFAULT_CARGO_PAGE_SIZE,
        budget: CargoCatalogBudget = CargoCatalogBudget(),
        timeout: float = 5.0,
        runtime_identity: RuntimeIdentity | None = None,
        world_id: str | None = None,
    ):
        catalog_request_id(session_id, budget.max_pages)
        CargoPageRequest(catalog_request_id(session_id, 1), None, page_size)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("positive finite timeout required")
        if world_id is not None:
            validate_request_id(world_id)
        self.session_id, self.page_size, self.budget, self.timeout = (
            session_id,
            page_size,
            budget,
            timeout,
        )
        self.runtime_identity, self.world_id = runtime_identity, world_id
        self._started = False
        self._events: list[str] = []
        self._exchanges: list[CargoPageExchange] = []
        self._digest: str | None = None
        self._failure: str | None = None

    @property
    def evidence(self) -> CargoCatalogSessionEvidence:
        return CargoCatalogSessionEvidence(
            self.session_id,
            tuple(self._events),
            tuple(self._exchanges),
            self._digest is not None,
            self._digest,
            self._failure,
        )

    async def collect(
        self,
        transport: CatalogTransport,
        native_evidence: Callable[
            [CargoPageRequest, CargoPageExchange], Awaitable[CargoPageEvidence]
        ],
    ) -> CargoCatalogObservation:
        if self._started:
            raise BridgeProtocolError("catalog session single-use; no retry/resume")
        self._started = True
        self._events.append("CARGO_CATALOG_SESSION_STARTED")
        connection = getattr(transport, "session", None)
        pages = []
        after = None
        count = 0
        try:
            for number in range(1, self.budget.max_pages + 1):
                remaining = self.budget.max_operations - sum(
                    e.protocol_operations for e in self._exchanges
                )
                if remaining < 4 or getattr(transport, "session", None) is not connection:
                    raise BridgeProtocolError(
                        "catalog connection changed or frame budget exhausted"
                    )
                if (
                    sum(len(e.response_payload) for e in self._exchanges)
                    >= self.budget.max_response_bytes
                ):
                    raise BridgeProtocolError("catalog byte budget exhausted")
                request = CargoPageRequest(
                    catalog_request_id(self.session_id, number), after, self.page_size
                )
                async with asyncio.timeout(self.timeout):
                    exchange = await transport.cargo_page(
                        request, timeout=self.timeout, operation_budget=remaining
                    )
                    if (
                        exchange.request_payload != request.to_bytes()
                        or getattr(transport, "session", None) is not connection
                    ):
                        raise BridgeProtocolError("catalog request/connection changed")
                    exchange.validate()
                    self._exchanges.append(exchange)
                    count += len(exchange.response.cargoes)
                    if (
                        count > self.budget.max_records
                        or sum(len(e.response_payload) for e in self._exchanges)
                        > self.budget.max_response_bytes
                        or sum(e.protocol_operations for e in self._exchanges)
                        > self.budget.max_operations
                    ):
                        raise BridgeProtocolError("catalog cumulative budget exhausted")
                    native = await native_evidence(request, exchange)
                    if getattr(transport, "session", None) is not connection:
                        raise BridgeProtocolError("catalog connection changed; no resume")
                    page = CargoCatalogPage(exchange, native)
                    page.validate()
                    pages.append(page)
                    self._events.append("CARGO_PAGE_VALIDATED")
                response = exchange.response
                if not response.has_more:
                    self._events.append("FINAL_PAGE_VALIDATED")
                    observation = CargoCatalogObservation(
                        self.session_id,
                        tuple(pages),
                        self.budget,
                        self.runtime_identity,
                        self.world_id,
                    )
                    self._digest = observation.catalog_digest
                    self._events.extend(
                        ("CARGO_CATALOG_ASSEMBLED", "CARGO_CATALOG_SESSION_COMPLETED")
                    )
                    return observation
                if (
                    response.next_after_id is None
                    or after is not None
                    and response.next_after_id <= after
                ):
                    raise BridgeProtocolError("catalog cursor did not progress")
                after = response.next_after_id
            raise BridgeProtocolError("catalog page budget exhausted before terminal page")
        except BaseException as error:
            if isinstance(error, TimeoutError):
                error = TransportTimeout("catalog deadline expired")
            self._failure = f"{type(error).__name__}: {error}"
            self._events.append("CARGO_CATALOG_SESSION_FAILED")
            raise error
