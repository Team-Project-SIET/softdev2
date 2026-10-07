"""Bounded structural catalog collection and referential validation; no P08 adapter."""

import asyncio
import hashlib
import json
import math
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Protocol

from app.simulation.openttd.cargo_page import (
    DEFAULT_CARGO_PAGE_SIZE,
    CargoCatalogRecord,
    CargoPageExchange,
    CargoPageReceipt,
    CargoPageRequest,
)
from app.simulation.openttd.cargo_page_evidence import CargoPageEvidence
from app.simulation.openttd.gamescript_protocol import BridgeProtocolError, validate_request_id
from app.simulation.openttd.gamescript_transport import TransportTimeout
from app.simulation.openttd.industry_capability import IndustryCapabilityObservation
from app.simulation.openttd.runtime.identity import RuntimeIdentity


@dataclass(frozen=True)
class CargoCatalogBudget:
    max_pages: int = 64
    max_records: int = 64
    max_response_bytes: int = 32768
    max_operations: int = 512

    def __post_init__(self):
        for value, maximum in (
            (self.max_pages, 64),
            (self.max_records, 64),
            (self.max_response_bytes, 32768),
            (self.max_operations, 512),
        ):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("invalid catalog session budget")


def catalog_request_id(session_id: str, page: int) -> str:
    validate_request_id(session_id)
    if type(page) is not int or not 1 <= page <= 64:
        raise ValueError("invalid catalog page number")
    return validate_request_id(f"{session_id}-p{page:03d}")


@dataclass(frozen=True)
class CargoCatalogPage:
    exchange: CargoPageExchange
    gamescript: CargoPageEvidence

    @property
    def request(self) -> CargoPageRequest:
        return CargoPageRequest.parse(self.exchange.request_payload)

    def validate(self) -> None:
        self.exchange.validate()
        self.gamescript.require_complete(self.request, self.exchange.response)


@dataclass(frozen=True)
class CargoCatalogObservation:
    session_id: str
    pages: tuple[CargoCatalogPage, ...]
    budget: CargoCatalogBudget = CargoCatalogBudget()
    runtime_identity: RuntimeIdentity | None = None
    world_id: str | None = None  # Caller provenance, not a native snapshot/version claim.

    def __post_init__(self):
        validate_request_id(self.session_id)
        if self.world_id is not None:
            validate_request_id(self.world_id)
        if self.runtime_identity is not None and not isinstance(
            self.runtime_identity, RuntimeIdentity
        ):
            raise ValueError("invalid runtime identity")
        if (
            not isinstance(self.budget, CargoCatalogBudget)
            or type(self.pages) is not tuple
            or not self.pages
        ):
            raise ValueError("complete catalog requires immutable pages and a terminal page")
        after = None
        for number, page in enumerate(self.pages, 1):
            page.validate()
            q = page.request
            r = page.exchange.response
            if q.request_id != catalog_request_id(self.session_id, number) or q.after_id != after:
                raise ValueError("catalog cursor/request chain mismatch")
            if r.has_more != (number < len(self.pages)):
                raise ValueError("catalog requires exactly one terminal page")
            after = r.next_after_id
        ids = [r.cargo_id for r in self.records]
        if ids != sorted(set(ids)):
            raise ValueError("duplicate/nonascending catalog ID")
        if (
            self.page_count > self.budget.max_pages
            or len(ids) > self.budget.max_records
            or self.total_response_bytes > self.budget.max_response_bytes
            or self.protocol_operations > self.budget.max_operations
        ):
            raise ValueError("catalog observation exceeds session budget")

    @property
    def records(self) -> tuple[CargoCatalogRecord, ...]:
        return tuple(r for p in self.pages for r in p.exchange.response.cargoes)

    @property
    def complete(self) -> bool:
        return True  # Only a validated terminal chain constructs this observation.

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def first_cargo_id(self) -> int | None:
        return self.records[0].cargo_id if self.records else None

    @property
    def last_cargo_id(self) -> int | None:
        return self.records[-1].cargo_id if self.records else None

    @property
    def total_response_bytes(self) -> int:
        return sum(len(p.exchange.response_payload) for p in self.pages)

    @property
    def protocol_operations(self) -> int:
        return sum(p.exchange.protocol_operations for p in self.pages)

    @property
    def page_receipts(self) -> tuple[CargoPageReceipt, ...]:
        return tuple(p.exchange.receipt for p in self.pages)

    def to_bytes(self) -> bytes:
        return json.dumps(
            [asdict(r) for r in self.records], sort_keys=True, separators=(",", ":")
        ).encode("ascii")

    @property
    def catalog_digest(self) -> str:
        return hashlib.sha256(self.to_bytes()).hexdigest()


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


def validate_capability_catalog(
    capability: IndustryCapabilityObservation, catalog: CargoCatalogObservation
) -> None:
    """Existence/metadata validation only; no independent industry relationship claim."""
    if (
        not isinstance(capability, IndustryCapabilityObservation)
        or not isinstance(catalog, CargoCatalogObservation)
        or not capability.complete
        or not catalog.complete
    ):
        raise ValueError("complete capability and catalog observations required")
    ids = {r.cargo_id for r in catalog.records}
    referenced = {
        cargo for record in capability.capabilities for cargo in (*record.produces, *record.accepts)
    }
    missing = sorted(referenced - ids)
    if missing:
        raise ValueError(f"missing catalog cargo IDs: {missing}")
