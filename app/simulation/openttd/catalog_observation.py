"""Immutable observation types and validation; no execution dependencies."""

import hashlib
import json
from dataclasses import asdict, dataclass

from app.simulation.openttd.capability_observation import IndustryCapabilityObservation
from app.simulation.openttd.cargo_page import (
    CargoCatalogRecord,
    CargoPageExchange,
    CargoPageReceipt,
    CargoPageRequest,
)
from app.simulation.openttd.cargo_page_evidence import CargoPageEvidence
from app.simulation.openttd.observation_identity import RuntimeIdentity
from app.simulation.openttd.observation_protocol import validate_request_id


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
