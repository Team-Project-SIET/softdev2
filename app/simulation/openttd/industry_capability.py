"""Immutable normalized capability enrichment; no P08 mapping or transport-global state."""

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from app.simulation.openttd.capability_observation import (
    CapabilityBudget as CapabilityBudget,
)
from app.simulation.openttd.capability_observation import (
    CapabilityTransaction as CapabilityTransaction,
)
from app.simulation.openttd.capability_observation import (
    IndustryCapabilityObservation as IndustryCapabilityObservation,
)
from app.simulation.openttd.capability_observation import (
    capability_request_id as capability_request_id,
)
from app.simulation.openttd.gamescript_protocol import BridgeProtocolError, validate_request_id
from app.simulation.openttd.gamescript_transport import TransportTimeout
from app.simulation.openttd.industry_cargo import (
    IndustryCargoCapability as IndustryCargoCapability,
)
from app.simulation.openttd.industry_cargo import (
    IndustryCargoExchange,
    IndustryCargoRequest,
)
from app.simulation.openttd.industry_cargo_evidence import IndustryCargoEvidence
from app.simulation.openttd.industry_inventory import IndustryInventoryObservation


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
