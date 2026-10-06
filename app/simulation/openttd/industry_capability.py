"""Immutable normalized capability enrichment; no P08 mapping or transport-global state."""

import asyncio
import hashlib
import json
import math
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Protocol

from app.simulation.openttd.gamescript_protocol import BridgeProtocolError, validate_request_id
from app.simulation.openttd.gamescript_transport import TransportTimeout
from app.simulation.openttd.industry_cargo import (
    IndustryCargoCapability,
    IndustryCargoExchange,
    IndustryCargoRequest,
)
from app.simulation.openttd.industry_cargo_evidence import IndustryCargoEvidence
from app.simulation.openttd.industry_inventory import IndustryInventoryObservation


@dataclass(frozen=True)
class CapabilityBudget:
    max_industries: int = 32
    max_requests: int = 32
    max_response_bytes: int = 16384
    max_operations: int = 256

    def __post_init__(self):
        for value, maximum in (
            (self.max_industries, 32),
            (self.max_requests, 32),
            (self.max_response_bytes, 16384),
            (self.max_operations, 256),
        ):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("invalid capability session budget")


def capability_request_id(session_id: str, industry_id: int) -> str:
    validate_request_id(session_id)
    request_id = validate_request_id(f"{session_id}-i{industry_id:05d}")
    IndustryCargoRequest(request_id, industry_id)
    return request_id


@dataclass(frozen=True)
class CapabilityTransaction:
    exchange: IndustryCargoExchange
    native: IndustryCargoEvidence

    def validate(self):
        self.exchange.validate()
        self.native.require_complete(
            IndustryCargoRequest.parse(self.exchange.request_payload), self.exchange.response
        )


@dataclass(frozen=True)
class IndustryCapabilityObservation:
    session_id: str
    inventory: IndustryInventoryObservation
    transactions: tuple[CapabilityTransaction, ...]
    budget: CapabilityBudget = CapabilityBudget()

    def __post_init__(self):
        validate_request_id(self.session_id)
        if type(self.transactions) is not tuple or not isinstance(
            self.inventory, IndustryInventoryObservation
        ):
            raise ValueError("immutable inventory/transactions required")
        ids = []
        for transaction in self.transactions:
            transaction.validate()
            request = IndustryCargoRequest.parse(transaction.exchange.request_payload)
            if request.request_id != capability_request_id(self.session_id, request.industry_id):
                raise ValueError("capability request identity mismatch")
            ids.append(request.industry_id)
        if len(ids) != len(set(ids)) or set(ids) != {r.id for r in self.inventory.records}:
            raise ValueError("missing/extra/duplicate inventory capability")
        if (
            len(ids) > min(self.budget.max_industries, self.budget.max_requests)
            or self.total_response_bytes > self.budget.max_response_bytes
            or self.protocol_operations > self.budget.max_operations
        ):
            raise ValueError("capability session budget exhausted")

    @property
    def capabilities(self) -> tuple[IndustryCargoCapability, ...]:
        return tuple(
            sorted(
                (t.exchange.response.capability for t in self.transactions),
                key=lambda c: c.industry_id,
            )
        )

    @property
    def complete(self) -> bool:
        return True

    @property
    def total_response_bytes(self) -> int:
        return sum(len(t.exchange.response_payload) for t in self.transactions)

    @property
    def protocol_operations(self) -> int:
        return sum(t.exchange.protocol_operations for t in self.transactions)

    def to_bytes(self) -> bytes:
        return json.dumps(
            [asdict(c) for c in self.capabilities], sort_keys=True, separators=(",", ":")
        ).encode("ascii")

    @property
    def capability_digest(self) -> str:
        return hashlib.sha256(self.to_bytes()).hexdigest()


class CargoTransport(Protocol):
    async def industry_cargo(
        self, request: IndustryCargoRequest, *, timeout: float, operation_budget: int | None = None
    ) -> IndustryCargoExchange: ...


@dataclass(frozen=True)
class CapabilitySessionEvidence:
    session_id: str
    events: tuple[str, ...]
    exchanges: tuple[IndustryCargoExchange, ...]
    complete: bool
    capability_digest: str | None
    failure: str | None


class IndustryCapabilitySession:
    def __init__(
        self,
        session_id: str,
        inventory: IndustryInventoryObservation,
        *,
        budget: CapabilityBudget = CapabilityBudget(),
        timeout: float = 5.0,
    ):
        validate_request_id(session_id)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("positive finite timeout required")
        self.session_id, self.inventory, self.budget, self.timeout = (
            session_id,
            inventory,
            budget,
            timeout,
        )
        self._started = False
        self._events: list[str] = []
        self._exchanges: list[IndustryCargoExchange] = []
        self._digest: str | None = None
        self._failure: str | None = None

    @property
    def evidence(self) -> CapabilitySessionEvidence:
        return CapabilitySessionEvidence(
            self.session_id,
            tuple(self._events),
            tuple(self._exchanges),
            self._digest is not None,
            self._digest,
            self._failure,
        )

    async def collect(
        self,
        transport: CargoTransport,
        native_evidence: Callable[
            [IndustryCargoRequest, IndustryCargoExchange], Awaitable[IndustryCargoEvidence]
        ],
    ) -> IndustryCapabilityObservation:
        if self._started:
            raise BridgeProtocolError("capability session single-use; no retry/resume")
        self._started = True
        self._events.append("CAPABILITY_SESSION_STARTED")
        connection = getattr(transport, "session", None)
        transactions = []
        try:
            if len(self.inventory.records) > min(
                self.budget.max_industries, self.budget.max_requests
            ):
                raise BridgeProtocolError("capability query budget exhausted")
            requests = [
                IndustryCargoRequest(capability_request_id(self.session_id, r.id), r.id)
                for r in self.inventory.records
            ]
            for request in requests:
                remaining = self.budget.max_operations - sum(
                    e.protocol_operations for e in self._exchanges
                )
                if remaining < 4 or getattr(transport, "session", None) is not connection:
                    raise BridgeProtocolError(
                        "capability connection changed or operation budget exhausted"
                    )
                async with asyncio.timeout(self.timeout):
                    exchange = await transport.industry_cargo(
                        request, timeout=self.timeout, operation_budget=remaining
                    )
                    if (
                        getattr(transport, "session", None) is not connection
                        or exchange.request_payload != request.to_bytes()
                    ):
                        raise BridgeProtocolError("capability connection/request changed")
                    exchange.validate()
                    self._exchanges.append(exchange)
                    if (
                        sum(len(e.response_payload) for e in self._exchanges)
                        > self.budget.max_response_bytes
                        or sum(e.protocol_operations for e in self._exchanges)
                        > self.budget.max_operations
                    ):
                        raise BridgeProtocolError("capability cumulative budget exhausted")
                    native = await native_evidence(request, exchange)
                    if getattr(transport, "session", None) is not connection:
                        raise BridgeProtocolError("capability connection changed; no resume")
                    transaction = CapabilityTransaction(exchange, native)
                    transaction.validate()
                    transactions.append(transaction)
                    self._events.append("CAPABILITY_VALIDATED")
            result = IndustryCapabilityObservation(
                self.session_id, self.inventory, tuple(transactions), self.budget
            )
            self._digest = result.capability_digest
            self._events.extend(
                ("CAPABILITY_OBSERVATION_ASSEMBLED", "CAPABILITY_SESSION_COMPLETED")
            )
            return result
        except BaseException as error:
            if isinstance(error, TimeoutError):
                error = TransportTimeout("capability deadline expired")
            self._failure = f"{type(error).__name__}: {error}"
            self._events.append("CAPABILITY_SESSION_FAILED")
            raise error
