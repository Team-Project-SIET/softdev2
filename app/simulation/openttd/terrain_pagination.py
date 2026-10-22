"""Pure single-sweep page admission; no transport, native proof or planning authority."""

import hashlib
import json
from dataclasses import dataclass

from app.simulation.openttd.supplemental_planning_facts import Region
from app.simulation.openttd.tile_facts import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    PAGE_SIZE,
    TileFactsExchange,
    TileFactsRequest,
)

MAX_PAGES = 52


@dataclass(frozen=True)
class PaginationBudget:
    """One regional sweep ceilings from the P08 design; not native authorization."""

    max_pages: int = MAX_PAGES
    page_request_bytes: int = MAX_REQUEST_BYTES
    page_response_bytes: int = MAX_RESPONSE_BYTES
    max_request_bytes: int = MAX_PAGES * MAX_REQUEST_BYTES
    max_response_bytes: int = MAX_PAGES * MAX_RESPONSE_BYTES
    max_operations: int = MAX_PAGES * 8

    def __post_init__(self):
        for value, maximum in (
            (self.max_pages, MAX_PAGES),
            (self.page_request_bytes, MAX_REQUEST_BYTES),
            (self.page_response_bytes, MAX_RESPONSE_BYTES),
            (self.max_request_bytes, MAX_PAGES * MAX_REQUEST_BYTES),
            (self.max_response_bytes, MAX_PAGES * MAX_RESPONSE_BYTES),
            (self.max_operations, MAX_PAGES * 8),
        ):
            if type(value) is not int or not 0 < value <= maximum:
                raise ValueError("Invalid pagination budget")


@dataclass(frozen=True)
class TerrainDataset:
    rows: tuple[tuple[int | None, ...], ...]
    exchanges: tuple[TileFactsExchange, ...]

    @property
    def metadata(self) -> dict:
        request = TileFactsRequest.parse(self.exchanges[0].request_payload)
        return dict(
            complete=True,
            map=[self.exchanges[0].response.map_width, self.exchanges[0].response.map_height],
            mode="CONTROLLED_DATA_ASSEMBLY",
            region=[
                request.region.x,
                request.region.y,
                request.region.width,
                request.region.height,
            ],
            tile_count=len(self.rows),
            request_bytes=sum(len(e.request_payload) for e in self.exchanges),
            response_bytes=sum(len(e.response_payload) for e in self.exchanges),
            query_operations=sum(e.protocol_operations for e in self.exchanges),
            rows_sha256=hashlib.sha256(
                json.dumps(self.rows, separators=(",", ":")).encode("ascii")
            ).hexdigest(),
            pages=[
                dict(
                    request_id=e.receipt.request_id,
                    cursor=TileFactsRequest.parse(e.request_payload).cursor,
                    tile_ids=[r[0] for r in e.response.rows],
                    request_sha256=e.receipt.request_payload_sha256,
                    response_sha256=e.receipt.response_payload_sha256,
                    request_bytes=len(e.request_payload),
                    response_bytes=len(e.response_payload),
                    query_operations=e.protocol_operations,
                )
                for e in self.exchanges
            ],
            expected_pages=[e.receipt.request_id for e in self.exchanges],
            received_pages=[e.receipt.request_id for e in self.exchanges],
        )


class TerrainPagination:
    """Accept pages only in enumeration order; partial coverage never produces a dataset."""

    def __init__(
        self,
        region: Region,
        width: int,
        height: int,
        *,
        request_prefix="terrain",
        budget: PaginationBudget = PaginationBudget(),
    ):
        if not isinstance(budget, PaginationBudget):
            raise ValueError("Invalid pagination budget")
        # Validate the region even when its area would enumerate no requests.
        TileFactsRequest(request_prefix + "-p001", region, 0).require_map(width, height)
        n = region.width * region.height
        self.requests = tuple(
            TileFactsRequest(f"{request_prefix}-p{i // PAGE_SIZE + 1:03d}", region, i)
            for i in range(0, n, PAGE_SIZE)
        )
        for request in self.requests:
            request.require_map(width, height)
        if len(self.requests) > budget.max_pages:
            raise ValueError("Page budget exhausted")
        self.budget = budget
        self.width, self.height = width, height
        self._exchanges: list[TileFactsExchange] = []
        self._failed = False

    @property
    def progress(self) -> dict:
        expected = [q.request_id for q in self.requests]
        received = [e.receipt.request_id for e in self._exchanges]
        return dict(
            expected_pages=expected,
            received_pages=received,
            missing_pages=expected[len(received) :],
            failed=self._failed,
        )

    def accept(self, exchange: TileFactsExchange) -> None:
        try:
            if self._failed or len(self._exchanges) >= len(self.requests):
                raise ValueError("Duplicate or failed page admission")
            if not isinstance(exchange, TileFactsExchange):
                raise ValueError("Malformed page exchange")
            if (
                type(exchange.request_payload) is not bytes
                or type(exchange.response_payload) is not bytes
            ):
                raise ValueError("Page payloads must be immutable bytes")
            exchange.validate()
            if (
                len(exchange.request_payload) > self.budget.page_request_bytes
                or len(exchange.response_payload) > self.budget.page_response_bytes
                or sum(len(e.request_payload) for e in self._exchanges)
                + len(exchange.request_payload)
                > self.budget.max_request_bytes
                or sum(len(e.response_payload) for e in self._exchanges)
                + len(exchange.response_payload)
                > self.budget.max_response_bytes
                or sum(e.protocol_operations for e in self._exchanges)
                + exchange.protocol_operations
                > self.budget.max_operations
            ):
                raise ValueError("Pagination budget exhausted")
            if exchange.request_payload != self.requests[len(self._exchanges)].to_bytes():
                raise ValueError("Incorrect page identity or ordering")
            response = exchange.response
            if (response.map_width, response.map_height) != (self.width, self.height):
                raise ValueError("Incorrect map identity")
            self._exchanges.append(exchange)
        except (ValueError, TypeError, AttributeError) as error:
            self._failed = True
            raise ValueError("Page admission failed: " + str(error)) from error

    def finish(self) -> TerrainDataset:
        if self._failed or len(self._exchanges) != len(self.requests):
            raise ValueError("Incomplete or failed coverage")
        return TerrainDataset(
            tuple(row for e in self._exchanges for row in e.response.rows),
            tuple(self._exchanges),
        )
