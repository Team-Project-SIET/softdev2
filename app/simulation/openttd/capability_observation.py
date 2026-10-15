"""Immutable observation types and validation; no execution dependencies."""

import hashlib
import json
from dataclasses import asdict, dataclass

from app.simulation.openttd.industry_cargo import (
    IndustryCargoCapability,
    IndustryCargoExchange,
    IndustryCargoRequest,
)
from app.simulation.openttd.industry_cargo_evidence import IndustryCargoEvidence
from app.simulation.openttd.industry_inventory import IndustryInventoryObservation
from app.simulation.openttd.observation_protocol import validate_request_id


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
