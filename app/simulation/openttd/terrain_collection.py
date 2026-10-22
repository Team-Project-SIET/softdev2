"""Bounded two-sweep acquisition on a supplied client; never opens a connection."""

import asyncio
import hashlib
import json
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Protocol

from app.simulation.openttd.prepared_source_correspondence import SourceTrust
from app.simulation.openttd.structural_world import StructuralWorldContext
from app.simulation.openttd.supplemental_planning_facts import (
    FactSource,
    Region,
    SupplementalPlanningFacts,
    TileFact,
)
from app.simulation.openttd.tile_facts import (
    PAGE_SIZE,
    TileFactsExchange,
    TileFactsRequest,
    TileFailure,
    TileQueryError,
    integer,
)
from app.simulation.openttd.tile_facts_evidence import TileFactsEvidence
from app.simulation.openttd.world_planning_observation import WorldPlanningObservation


class TerrainFrames(Protocol):
    """Existing secure-session observer; receipts reconcile, never increment it."""

    @property
    def query_operations(self) -> int: ...
    @property
    def total_frames(self) -> int: ...
    @property
    def failed(self) -> bool: ...
    def enter(self, phase: str) -> None: ...


class TerrainClient(Protocol):
    @property
    def context(self) -> StructuralWorldContext: ...
    @property
    def session(self) -> object: ...
    @property
    def frame_budget(self) -> TerrainFrames: ...

    async def tile_facts_page(
        self, request: TileFactsRequest, *, timeout: float, operation_budget: int
    ) -> TileFactsExchange: ...


@dataclass(frozen=True)
class TerrainBudget:
    max_requests: int = 104
    max_response_bytes: int = 52832
    max_operations: int = 832
    max_getter_calls: int = 23152

    def __post_init__(self):
        for n, ceiling in (
            (self.max_requests, 104),
            (self.max_response_bytes, 52832),
            (self.max_operations, 832),
            (self.max_getter_calls, 23152),
        ):
            if type(n) is not int or not 1 <= n <= ceiling:
                raise ValueError("invalid terrain budget")


@dataclass(frozen=True)
class TerrainObservation:
    world: WorldPlanningObservation
    source: FactSource
    region: Region
    tiles: tuple[TileFact, ...]
    diagnostic_rows: tuple[tuple[int | None, ...], ...]
    sweeps: tuple[tuple[TileFactsExchange, ...], ...]
    gamescript: tuple[TileFactsEvidence, ...]
    capture_economy_date_before: int
    capture_economy_date_after: int
    trust: SourceTrust = SourceTrust.CONTROLLED_FIXTURE

    def __post_init__(self):
        if self.trust is not SourceTrust.CONTROLLED_FIXTURE:
            raise TileQueryError(TileFailure.PROVENANCE_MISMATCH)
        replace(self.world)
        FactSource.model_validate_json(self.source.model_dump_json())
        self.source.require_world(self.world)
        if len(self.sweeps) != 2 or len(self.gamescript) != sum(len(s) for s in self.sweeps):
            raise TileQueryError(TileFailure.INCOMPLETE_SWEEP)
        month = self.world.production.qualification.current_month
        expected = tuple(
            y * self.source.map_width + x
            for y in range(self.region.y, self.region.y + self.region.height)
            for x in range(self.region.x, self.region.x + self.region.width)
        )
        all_rows = []
        all_tiles = []
        dates = []
        seen_ids = set()
        ev = iter(self.gamescript)
        for sweep in self.sweeps:
            rows = []
            tiles = []
            cursor = 0
            for ex in sweep:
                ex.validate()
                next(ev).require_complete(ex)
                q = TileFactsRequest.parse(ex.request_payload)
                r = ex.response
                if (
                    q.request_id in seen_ids
                    or q.region != self.region
                    or q.cursor != cursor
                    or (r.map_width, r.map_height)
                    != (self.source.map_width, self.source.map_height)
                ):
                    raise TileQueryError(TileFailure.CURSOR_MISMATCH)
                seen_ids.add(q.request_id)
                if not month.start_date <= r.date_before <= r.date_after < month.end_date or (
                    dates and r.date_before < dates[-1]
                ):
                    raise TileQueryError(TileFailure.ECONOMY_MONTH_CROSSING)
                dates.extend([r.date_before, r.date_after])
                rows.extend(r.rows)
                tiles.extend(r.tiles)
                cursor += len(r.rows)
            if (
                tuple(row[0] for row in rows) != expected
                or not sweep
                or sweep[-1].response.has_more
            ):
                raise TileQueryError(TileFailure.INCOMPLETE_SWEEP)
            all_rows.append(tuple(rows))
            all_tiles.append(tuple(tiles))
        if all_rows[0] != all_rows[1]:
            raise TileQueryError(TileFailure.SWEEP_DRIFT)
        if (
            self.diagnostic_rows != all_rows[0]
            or self.tiles != all_tiles[0]
            or (self.capture_economy_date_before, self.capture_economy_date_after)
            != (dates[0], dates[-1])
        ):
            raise TileQueryError(TileFailure.INCOMPLETE_SWEEP)
        ids = {i.id for i in self.world.structural.inventory.observation.records}
        if any(t.industry_id is not None and t.industry_id not in ids for t in self.tiles):
            raise TileQueryError(TileFailure.PROVENANCE_MISMATCH)
        # Reciprocal directed diagnostics must agree, without claiming a YAPF route.
        byid = {row[0]: row for row in self.diagnostic_rows}
        for row in self.diagnostic_rows:
            tile = integer(row[0], 0, 16777215)
            for bit, delta in enumerate((-self.source.map_width, 1, self.source.map_width, -1)):
                if integer(row[9], 0, 15) & (1 << bit):
                    neighbor = byid[tile + delta]
                    opposite = (bit + 2) % 4
                    if bool(integer(row[7], 0, 15) & (1 << bit)) != bool(
                        integer(neighbor[8], 0, 15) & (1 << opposite)
                    ) or bool(integer(row[8], 0, 15) & (1 << bit)) != bool(
                        integer(neighbor[7], 0, 15) & (1 << opposite)
                    ):
                        raise TileQueryError(TileFailure.SWEEP_DRIFT)

    @property
    def semantic_digest(self):
        value = dict(
            source=self.source.model_dump(mode="json"),
            region=self.region.model_dump(mode="json"),
            rows=self.diagnostic_rows,
            policy="terrain-two-sweep-v1",
            trust=self.trust.value,
        )
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def require_supplemental(self, facts: SupplementalPlanningFacts):
        """Check independently complete bundle; never invent deferred fields."""
        replace(self)
        facts.require_world(self.world)
        if (
            facts.source != self.source
            or facts.region != self.region
            or facts.tiles != self.tiles
            or (facts.capture_economy_date_before, facts.capture_economy_date_after)
            != (self.capture_economy_date_before, self.capture_economy_date_after)
        ):
            raise TileQueryError(TileFailure.PROVENANCE_MISMATCH)


class TerrainCollector:
    """Single-use, fail-closed; retained partial evidence is never accepted output."""

    def __init__(
        self,
        world: WorldPlanningObservation,
        source: FactSource,
        region: Region,
        *,
        session_id: str = "terrain-001",
        budget: TerrainBudget = TerrainBudget(),
        timeout: float = 5.0,
    ):
        replace(world)
        if not isinstance(source, FactSource) or not isinstance(budget, TerrainBudget):
            raise TileQueryError(TileFailure.PROVENANCE_MISMATCH)
        FactSource.model_validate_json(source.model_dump_json())
        replace(budget)
        source.require_world(world)
        TileFactsRequest(session_id + "-s2-p052", region, 0).require_map(
            source.map_width, source.map_height
        )
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("invalid timeout")
        self.world, self.source, self.region = world, source, region
        self.session_id, self.budget, self.timeout = session_id, budget, timeout
        self.started = False
        self.result = None
        self.failure = None
        self.requests = 0
        self.response_bytes = 0
        self.operations = 0
        self.getter_calls = 0
        self.exchanges = []
        self.evidence = []
        self.phase_counts = [dict(requests=0, bytes=0, operations=0, getters=0) for _ in range(2)]

    def check(self, client: TerrainClient, session: object):
        if (
            client.session is not session
            or client.context.connection_identity is not self.world.context.connection_identity
        ):
            raise TileQueryError(TileFailure.CONNECTION_REPLACED)
        try:
            self.world.context.require_same_run(client.context)
        except ValueError as e:
            raise TileQueryError(TileFailure.PROVENANCE_MISMATCH) from e

    async def collect(
        self,
        client: TerrainClient,
        evidence: Callable[[TileFactsRequest, TileFactsExchange], Awaitable[TileFactsEvidence]],
        *,
        phase_started: Callable[[str], None] | None = None,
    ) -> TerrainObservation:
        if self.started:
            raise TileQueryError(TileFailure.INCOMPLETE_SWEEP)
        self.started = True
        session = client.session
        sweeps = []
        frames = client.frame_budget
        initial_operations = frames.query_operations
        try:
            self.check(client, session)
            for index in range(2):
                frames.enter("sweep" + str(index + 1))
                if phase_started:
                    phase_started("sweep" + str(index + 1))
                phase = self.phase_counts[index]
                completed = []
                cursor = 0
                n = self.region.width * self.region.height
                while cursor < n:
                    self.check(client, session)
                    count = min(PAGE_SIZE, n - cursor)
                    work = count * 44 + 6
                    if (
                        self.requests >= self.budget.max_requests
                        or self.response_bytes + 508 > self.budget.max_response_bytes
                        or self.operations + 4 > self.budget.max_operations
                        or self.getter_calls + work > self.budget.max_getter_calls
                        or phase["requests"] >= 52
                        or phase["bytes"] + 508 > 26416
                        or phase["operations"] + 4 > 416
                    ):
                        raise TileQueryError(TileFailure.ACCOUNTING_LIMIT_EXCEEDED)
                    q = TileFactsRequest(
                        f"{self.session_id}-s{index + 1}-p{cursor // 5 + 1:03d}",
                        self.region,
                        cursor,
                    )
                    self.requests += 1
                    phase["requests"] += 1
                    self.getter_calls += work
                    phase["getters"] += work
                    async with asyncio.timeout(self.timeout):
                        ex = await client.tile_facts_page(
                            q,
                            timeout=self.timeout,
                            operation_budget=min(
                                8,
                                self.budget.max_operations - self.operations,
                                416 - phase["operations"],
                            ),
                        )
                    self.exchanges.append(ex)
                    self.response_bytes += len(ex.response_payload)
                    phase["bytes"] += len(ex.response_payload)
                    self.operations += ex.protocol_operations
                    phase["operations"] += ex.protocol_operations
                    if (
                        self.response_bytes > self.budget.max_response_bytes
                        or self.operations > self.budget.max_operations
                        or phase["bytes"] > 26416
                        or phase["operations"] > 416
                    ):
                        raise TileQueryError(TileFailure.ACCOUNTING_LIMIT_EXCEEDED)
                    if (
                        client.frame_budget is not frames
                        or frames.failed
                        or frames.total_frames > 838
                        or frames.query_operations - initial_operations != self.operations
                    ):
                        raise TileQueryError(TileFailure.ACCOUNTING_LIMIT_EXCEEDED)
                    self.check(client, session)
                    ex.validate()
                    if ex.request_payload != q.to_bytes():
                        raise TileQueryError(TileFailure.CURSOR_MISMATCH)
                    r = ex.response
                    month = self.world.production.qualification.current_month
                    if (r.map_width, r.map_height) != (
                        self.source.map_width,
                        self.source.map_height,
                    ):
                        raise TileQueryError(TileFailure.PROVENANCE_MISMATCH)
                    previous = (
                        self.exchanges[-2].response.date_after
                        if len(self.exchanges) > 1
                        else month.start_date
                    )
                    if (
                        not month.start_date <= r.date_before <= r.date_after < month.end_date
                        or r.date_before < previous
                    ):
                        raise TileQueryError(TileFailure.ECONOMY_MONTH_CROSSING)
                    async with asyncio.timeout(self.timeout):
                        ev = await evidence(q, ex)
                    self.evidence.append(ev)
                    self.check(client, session)
                    ev.require_complete(ex)
                    completed.append(ex)
                    cursor += len(ex.response.rows)
                sweeps.append(tuple(completed))
            first = sweeps[0]
            last = sweeps[-1]
            result = TerrainObservation(
                self.world,
                self.source,
                self.region,
                tuple(t for ex in first for t in ex.response.tiles),
                tuple(r for ex in first for r in ex.response.rows),
                tuple(sweeps),
                tuple(self.evidence),
                first[0].response.date_before,
                last[-1].response.date_after,
            )
            self.result = result
            return result
        except BaseException as e:
            self.failure = str(e)
            raise
