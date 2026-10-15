"""Immutable bounded world observations, separate from planning/preparation models."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from app.simulation.openttd.industry_page import (
    IndustryPageExchange,
    IndustryPageReceipt,
    IndustryPageRequest,
    IndustryRecord,
)
from app.simulation.openttd.industry_page_evidence import IndustryPageEvidence
from app.simulation.openttd.observation_identity import RuntimeIdentity
from app.simulation.openttd.observation_protocol import (
    MAX_PAYLOAD_BYTES,
    BridgeProtocolError,
    validate_request_id,
)
from app.simulation.openttd.world_info import WorldInfoResponse

if TYPE_CHECKING:
    from app.simulation.openttd.admin_protocol import ServerWelcome


DEFAULT_INDUSTRY_PAGE_SIZE = 3
MAX_INDUSTRY_RECORDS = 32  # P08 v1 profile authority; no domain import.
MAX_INDUSTRY_PAGES = MAX_INDUSTRY_RECORDS  # Supports the minimum page size of one.
MAX_INDUSTRY_SESSION_BYTES = MAX_INDUSTRY_PAGES * MAX_PAYLOAD_BYTES
MAX_INDUSTRY_OPERATIONS = MAX_INDUSTRY_PAGES * 8


@dataclass(frozen=True)
class IndustryInventoryBudget:
    max_pages: int = MAX_INDUSTRY_PAGES
    max_records: int = MAX_INDUSTRY_RECORDS
    max_response_bytes: int = MAX_INDUSTRY_SESSION_BYTES
    max_operations: int = MAX_INDUSTRY_OPERATIONS

    def __post_init__(self) -> None:
        for value, ceiling in (
            (self.max_pages, MAX_INDUSTRY_PAGES),
            (self.max_records, MAX_INDUSTRY_RECORDS),
            (self.max_response_bytes, MAX_INDUSTRY_SESSION_BYTES),
            (self.max_operations, MAX_INDUSTRY_OPERATIONS),
        ):
            if type(value) is not int or not 1 <= value <= ceiling:
                raise ValueError("invalid inventory session budget")


def inventory_request_id(session_id: str, page: int) -> str:
    validate_request_id(session_id)
    if type(page) is not int or not 1 <= page <= MAX_INDUSTRY_PAGES:
        raise ValueError("invalid inventory page number")
    return validate_request_id(f"{session_id}-p{page:03d}")


@dataclass(frozen=True)
class IndustryInventoryWorld:
    world_id: str
    runtime_identity: RuntimeIdentity
    map_width: int
    map_height: int

    def __post_init__(self) -> None:
        validate_request_id(self.world_id)
        self.dimensions

    @property
    def dimensions(self) -> WorldInfoResponse:
        return WorldInfoResponse(self.world_id, self.map_width, self.map_height)

    @classmethod
    def from_welcome(
        cls, world_id: str, runtime: RuntimeIdentity, welcome: ServerWelcome
    ) -> IndustryInventoryWorld:
        """Caller supplies WELCOME from its authenticated encrypted Admin connection."""
        if welcome.revision != runtime.version or not welcome.dedicated:
            raise ValueError("runtime identity/WELCOME mismatch")
        return cls(world_id, runtime, welcome.width, welcome.height)


@dataclass(frozen=True)
class IndustryInventoryPage:
    exchange: IndustryPageExchange
    gamescript: IndustryPageEvidence

    @property
    def request(self) -> IndustryPageRequest:
        return IndustryPageRequest.parse(self.exchange.request_payload)

    def validate(self, world: WorldInfoResponse) -> None:
        self.exchange.validate(world)
        self.gamescript.require_complete(self.request, self.exchange.response)


@dataclass(frozen=True)
class IndustryInventorySessionEvidence:
    session_id: str
    events: tuple[str, ...]
    request_ids: tuple[str, ...]
    request_digests: tuple[str, ...]
    response_digests: tuple[str, ...]
    requested_cursors: tuple[int | None, ...]
    next_cursors: tuple[int | None, ...]
    total_records: int
    total_response_bytes: int
    protocol_operations: int
    final_has_more: bool | None
    inventory_digest: str | None
    failure: str | None = None

    @property
    def page_count(self) -> int:
        return len(self.request_ids)


@dataclass(frozen=True)
class IndustryInventoryObservation:
    session_id: str
    world: IndustryInventoryWorld
    pages: tuple[IndustryInventoryPage, ...]
    budget: IndustryInventoryBudget = IndustryInventoryBudget()

    def __post_init__(self) -> None:
        if type(self.pages) is not tuple or not self.pages:
            raise BridgeProtocolError("complete inventory requires a final page")
        after = None
        last_id = None
        for number, page in enumerate(self.pages, 1):
            page.validate(self.world.dimensions)
            request, response = page.request, page.exchange.response
            if request.request_id != inventory_request_id(self.session_id, number) or (
                request.after_id != after
            ):
                raise BridgeProtocolError("inventory cursor/request identity chain mismatch")
            for record in response.industries:
                if last_id is not None and record.id <= last_id:
                    raise BridgeProtocolError("duplicate/non-ascending inventory ID")
                last_id = record.id
            if response.has_more != (number < len(self.pages)):
                raise BridgeProtocolError("complete inventory requires exactly one terminal page")
            after = response.next_after_id
        if (
            self.page_count > self.budget.max_pages
            or len(self.records) > self.budget.max_records
            or self.total_response_bytes > self.budget.max_response_bytes
            or self.protocol_operations > self.budget.max_operations
        ):
            raise BridgeProtocolError("inventory observation exceeds session budget")

    @property
    def records(self) -> tuple[IndustryRecord, ...]:
        return tuple(record for page in self.pages for record in page.exchange.response.industries)

    @property
    def complete(self) -> bool:
        return True  # Construction requires the entire validated terminal chain.

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def first_industry_id(self) -> int | None:
        return self.records[0].id if self.records else None

    @property
    def last_industry_id(self) -> int | None:
        return self.records[-1].id if self.records else None

    @property
    def total_response_bytes(self) -> int:
        return sum(len(page.exchange.response_payload) for page in self.pages)

    @property
    def protocol_operations(self) -> int:
        return sum(page.exchange.protocol_operations for page in self.pages)

    @property
    def page_receipts(self) -> tuple[IndustryPageReceipt, ...]:
        return tuple(page.exchange.receipt for page in self.pages)

    def to_bytes(self) -> bytes:
        """Inventory identity excludes session IDs, paths, timestamps and logs."""
        return json.dumps(
            [asdict(record) for record in self.records], sort_keys=True, separators=(",", ":")
        ).encode("ascii")

    @property
    def inventory_digest(self) -> str:
        return hashlib.sha256(self.to_bytes()).hexdigest()
