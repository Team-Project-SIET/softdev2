"""Same-run two-phase observation; Python owns assembly, no retry/resume or P08 mapping."""

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol

from app.simulation.openttd.gamescript_bridge import BridgePackage
from app.simulation.openttd.gamescript_protocol import BridgeProtocolError
from app.simulation.openttd.industry_capability import (
    CargoTransport,
    IndustryCapabilityObservation,
    IndustryCapabilitySession,
)
from app.simulation.openttd.industry_inventory import IndustryInventoryWorld
from app.simulation.openttd.industry_query import IndustryInventorySession, IndustryPageTransport

ENRICHMENT_SESSION_ID = "openttd15-industry-enrichment-001"
ENRICHMENT_INVENTORY_ID = "openttd15-industry-inventory-001"


@dataclass(frozen=True)
class EnrichmentBudget:
    max_requests: int = 64
    max_response_bytes: int = 32768
    max_operations: int = 512

    def __post_init__(self):
        for value, ceiling in (
            (self.max_requests, 64),
            (self.max_response_bytes, 32768),
            (self.max_operations, 512),
        ):
            if type(value) is not int or not 1 <= value <= ceiling:
                raise ValueError("invalid combined enrichment budget")


class EnrichmentTransport(IndustryPageTransport, CargoTransport, Protocol):
    pass


class BoundedEnrichmentTransport:
    def __init__(self, transport, owner):
        self.transport, self.owner = transport, owner

    @property
    def session(self):
        return getattr(self.transport, "session", None)

    def claim(self):
        self.owner.check(self.transport, self.owner.connection)
        if self.owner.request_attempts >= self.owner.budget.max_requests:
            raise BridgeProtocolError("combined request budget exhausted before send")
        remaining = self.owner.budget.max_operations - self.owner.operations_used
        if remaining < 4:
            raise BridgeProtocolError("combined Admin frame budget exhausted before send")
        self.owner.request_attempts += 1
        return remaining

    async def industry_page(self, *args, **kwargs):
        if self.owner.inventory is not None:
            raise BridgeProtocolError("inventory phase already completed")
        remaining = self.claim()
        kwargs["operation_budget"] = min(kwargs.get("operation_budget") or remaining, remaining)
        return await self.transport.industry_page(*args, **kwargs)

    async def industry_cargo(self, *args, **kwargs):
        if self.owner.inventory is None or "CAPABILITY_PHASE_STARTED" not in self.owner.events:
            raise BridgeProtocolError("capability before complete same-run inventory")
        remaining = self.claim()
        kwargs["operation_budget"] = min(kwargs.get("operation_budget") or remaining, remaining)
        return await self.transport.industry_cargo(*args, **kwargs)


@dataclass(frozen=True)
class IndustryEnrichmentObservation:
    capability: IndustryCapabilityObservation
    bridge_identity: BridgePackage
    budget: EnrichmentBudget = EnrichmentBudget()

    def __post_init__(self):
        inventory = self.capability.inventory
        ids = tuple(r.id for r in inventory.records)
        queried = tuple(
            t.exchange.response.capability.industry_id for t in self.capability.transactions
        )
        if ids != queried or self.capability.session_id != ENRICHMENT_SESSION_ID:
            raise BridgeProtocolError("enrichment requires exact ordered same-inventory coverage")
        if (
            self.total_requests > self.budget.max_requests
            or self.total_response_bytes > self.budget.max_response_bytes
            or self.protocol_operations > self.budget.max_operations
        ):
            raise BridgeProtocolError("combined enrichment budget exhausted")

    @property
    def inventory(self):
        return self.capability.inventory

    @property
    def complete(self):
        return self.inventory.complete and self.capability.complete

    @property
    def source_inventory_digest(self):
        return self.inventory.inventory_digest

    @property
    def capability_digest(self):
        return self.capability.capability_digest

    @property
    def total_requests(self):
        return self.inventory.page_count + len(self.capability.transactions)

    @property
    def total_response_bytes(self):
        return self.inventory.total_response_bytes + self.capability.total_response_bytes

    @property
    def protocol_operations(self):
        return self.inventory.protocol_operations + self.capability.protocol_operations

    @property
    def enriched_digest(self):
        # Canonical logical observations only, independent of request IDs and page boundaries.
        raw = json.dumps(
            {
                "inventory_digest": self.source_inventory_digest,
                "capability_digest": self.capability_digest,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        return hashlib.sha256(raw).hexdigest()


class IndustryEnrichmentSession:
    """Always collect a fresh inventory from the same transport before capability phase."""

    def __init__(
        self,
        world: IndustryInventoryWorld,
        bridge: BridgePackage,
        *,
        budget: EnrichmentBudget = EnrichmentBudget(),
        timeout: float = 15,
    ):
        self.world, self.bridge, self.budget, self.timeout = world, bridge, budget, timeout
        self.inventory_session = IndustryInventorySession(
            ENRICHMENT_INVENTORY_ID, world, page_size=2, timeout=timeout
        )
        self.capability_session: IndustryCapabilitySession | None = None
        self.inventory = None
        self.observation = None
        self.events = []
        self.failure = None
        self._started = False
        self.request_attempts = 0
        self.connection = None

    @property
    def operations_used(self):
        pages = self.inventory_session.page_exchanges
        cargos = (
            () if self.capability_session is None else self.capability_session.evidence.exchanges
        )
        return sum(e.protocol_operations for e in (*pages, *cargos))

    def check(self, transport, connection):
        if getattr(transport, "session", None) is not connection:
            raise BridgeProtocolError("enrichment connection changed; no reconnect/resume")
        pages = self.inventory_session.page_exchanges
        cargos = (
            () if self.capability_session is None else self.capability_session.evidence.exchanges
        )
        if (
            len(pages) + len(cargos) > self.budget.max_requests
            or sum(len(e.response_payload) for e in (*pages, *cargos))
            > self.budget.max_response_bytes
            or sum(e.protocol_operations for e in (*pages, *cargos)) > self.budget.max_operations
        ):
            raise BridgeProtocolError("combined enrichment budget exhausted")

    async def collect(
        self, transport: EnrichmentTransport, page_evidence, cargo_evidence, begin_capability
    ):
        if self._started:
            raise BridgeProtocolError("enrichment single-use; no retry/resume")
        self._started = True
        connection = getattr(transport, "session", None)
        self.connection = connection
        bounded = BoundedEnrichmentTransport(transport, self)
        self.events.extend(("ENRICHMENT_SESSION_STARTED", "INVENTORY_SESSION_STARTED"))
        try:

            async def page(request, exchange):
                self.check(transport, connection)
                native = await page_evidence(request, exchange)
                self.check(transport, connection)
                native.require_complete(request, exchange.response)
                exchange.validate(self.world.dimensions)
                self.events.append("PAGE_VALIDATED")
                return native

            self.inventory = await self.inventory_session.collect(bounded, page)
            self.check(transport, connection)
            if not self.inventory.complete:
                raise BridgeProtocolError("complete same-run inventory required")
            self.events.append("INVENTORY_COMPLETED")
            if self.inventory.page_count + len(self.inventory.records) > self.budget.max_requests:
                raise BridgeProtocolError(
                    "combined request budget cannot cover observed industries"
                )
            begin_capability(self.inventory)
            self.check(transport, connection)
            self.events.append("CAPABILITY_PHASE_STARTED")
            self.capability_session = IndustryCapabilitySession(
                ENRICHMENT_SESSION_ID, self.inventory, timeout=self.timeout
            )

            async def cargo(request, exchange):
                self.check(transport, connection)
                native = await cargo_evidence(request, exchange)
                self.check(transport, connection)
                native.require_complete(request, exchange.response)
                exchange.validate()
                self.events.append("CAPABILITY_VALIDATED")
                return native

            capability = await self.capability_session.collect(bounded, cargo)
            self.check(transport, connection)
            result = IndustryEnrichmentObservation(capability, self.bridge, self.budget)
            self.observation = result
            self.events.extend(
                (
                    "CAPABILITY_OBSERVATION_ASSEMBLED",
                    "ENRICHMENT_VERIFIED",
                    "ENRICHMENT_SESSION_COMPLETED",
                )
            )
            return result
        except BaseException as error:
            self.failure = f"{type(error).__name__}: {error}"
            self.events.append("ENRICHMENT_SESSION_FAILED")
            raise
