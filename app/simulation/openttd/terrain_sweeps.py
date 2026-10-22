"""Pure controlled repeatability admission, not an atomic snapshot or native proof."""

import re
from dataclasses import dataclass

from app.simulation.openttd.supplemental_planning_facts import Region
from app.simulation.openttd.terrain_pagination import (
    PaginationBudget,
    TerrainDataset,
    TerrainPagination,
)
from app.simulation.openttd.tile_facts import TileFactsExchange, TileFactsRequest


@dataclass(frozen=True)
class TerrainSweepContext:
    acquisition_id: str
    world_fingerprint: str
    map_width: int
    map_height: int
    region: Region

    def __post_init__(self):
        if not isinstance(self.world_fingerprint, str) or not re.fullmatch(
            r"[0-9a-f]{64}", self.world_fingerprint
        ):
            raise ValueError("Invalid declared world fingerprint")
        TileFactsRequest(self.acquisition_id + "-s2-p052", self.region, 0).require_map(
            self.map_width, self.map_height
        )


@dataclass(frozen=True)
class TwoSweepBudget:
    max_pages: int = 104
    max_request_bytes: int = 16536
    max_response_bytes: int = 52832
    max_operations: int = 832

    def __post_init__(self):
        for value, maximum in (
            (self.max_pages, 104),
            (self.max_request_bytes, 16536),
            (self.max_response_bytes, 52832),
            (self.max_operations, 832),
        ):
            if type(value) is not int or not 0 < value <= maximum:
                raise ValueError("Invalid combined budget")


@dataclass(frozen=True)
class VerifiedTerrainPair:
    context: TerrainSweepContext
    sweeps: tuple[TerrainDataset, TerrainDataset]
    per_sweep_budget: PaginationBudget
    combined_budget: TwoSweepBudget

    @property
    def rows(self) -> tuple[tuple[int | None, ...], ...]:
        return self.sweeps[0].rows

    @property
    def metadata(self) -> dict:
        sweeps = [s.metadata for s in self.sweeps]
        return dict(
            mode="CONTROLLED_DATA_ASSEMBLY",
            world_fingerprint=self.context.world_fingerprint,
            acquisition_id=self.context.acquisition_id,
            complete=True,
            sweeps=sweeps,
            pages=sum(len(s.exchanges) for s in self.sweeps),
            request_bytes=sum(s["request_bytes"] for s in sweeps),
            response_bytes=sum(s["response_bytes"] for s in sweeps),
            query_operations=sum(s["query_operations"] for s in sweeps),
        )

    def verify(self) -> None:
        """Reparse and replay evidence; construction alone does not confer acceptance."""
        replay = TerrainTwoSweep(
            self.context,
            per_sweep_budget=self.per_sweep_budget,
            combined_budget=self.combined_budget,
        )
        for index, dataset in enumerate(self.sweeps, 1):
            for exchange in dataset.exchanges:
                replay.accept((self.context.acquisition_id, index), self.context, exchange)
            replay.complete_sweep()
        if replay.finish() != self:
            raise ValueError("Replayed pair differs from recorded evidence")


class TerrainTwoSweep:
    def __init__(
        self,
        context: TerrainSweepContext,
        *,
        per_sweep_budget: PaginationBudget = PaginationBudget(),
        combined_budget: TwoSweepBudget = TwoSweepBudget(),
    ):
        if not isinstance(context, TerrainSweepContext):
            raise ValueError("Invalid sweep context")
        context.__post_init__()
        if not isinstance(combined_budget, TwoSweepBudget):
            raise ValueError("Invalid combined budget")
        self._context = context
        self._budget = combined_budget
        self._per_sweep_budget = per_sweep_budget
        self._pages = tuple(
            TerrainPagination(
                context.region,
                context.map_width,
                context.map_height,
                request_prefix=context.acquisition_id + f"-s{i}",
                budget=per_sweep_budget,
            )
            for i in (1, 2)
        )
        if sum(len(p.requests) for p in self._pages) > combined_budget.max_pages:
            raise ValueError("Combined page budget exhausted")
        self._index = 0
        self._state = "FIRST_COLLECTING"
        self._datasets: list[TerrainDataset] = []
        self._evidence: list[TileFactsExchange] = []
        self._last_date: int | None = None
        self._reason: str | None = None
        self._result: VerifiedTerrainPair | None = None

    @property
    def state(self) -> str:
        return self._state

    @property
    def requests(self) -> tuple[TileFactsRequest, ...]:
        return self._pages[self._index].requests if self._state.endswith("COLLECTING") else ()

    @property
    def progress(self) -> dict:
        return dict(
            state=self._state,
            reason=self._reason,
            sweeps=[p.progress for p in self._pages],
            exchanges=tuple(self._evidence),
        )

    def _require_collecting(self) -> None:
        if not self._state.endswith("COLLECTING"):
            raise ValueError("Pair is " + self._state)

    def abort(self, reason: str) -> None:
        self._require_collecting()
        self._reason = reason
        self._state = "REJECTED"

    def accept(
        self,
        sweep: tuple[str, int],
        observed_context: TerrainSweepContext,
        exchange: TileFactsExchange,
    ) -> None:
        self._require_collecting()
        try:
            if (
                sweep != (self._context.acquisition_id, self._index + 1)
                or type(sweep[1]) is not int
            ):
                raise ValueError("Incorrect sweep identity")
            if observed_context != self._context:
                raise ValueError("Changed world or region context")
            exchange.validate()
            r = exchange.response
            if self._last_date is not None and r.date_before < self._last_date:
                raise ValueError("Regressing date bracket")
            evidence = (*self._evidence, exchange)
            if (
                len(evidence) > self._budget.max_pages
                or sum(len(e.request_payload) for e in evidence) > self._budget.max_request_bytes
                or sum(len(e.response_payload) for e in evidence) > self._budget.max_response_bytes
                or sum(e.protocol_operations for e in evidence) > self._budget.max_operations
            ):
                raise ValueError("Combined budget exhausted")
            self._pages[self._index].accept(exchange)
            self._evidence.append(exchange)
            self._last_date = r.date_after
        except (ValueError, TypeError, AttributeError, IndexError) as error:
            self.abort(str(error))
            raise ValueError("Sweep admission failed: " + str(error)) from error

    def complete_sweep(self) -> None:
        self._require_collecting()
        try:
            dataset = self._pages[self._index].finish()
            self._datasets.append(dataset)
            if self._index == 0:
                self._state = "FIRST_COMPLETE"
                self._index = 1
                self._state = "SECOND_COLLECTING"
            else:
                self._state = "VALIDATING_EQUALITY"
                if self._datasets[0].rows != dataset.rows:
                    raise ValueError("Terrain sweep drift")
                self._result = VerifiedTerrainPair(
                    self._context,
                    (self._datasets[0], dataset),
                    self._per_sweep_budget,
                    self._budget,
                )
                self._state = "ACCEPTED"
        except ValueError as error:
            self._state = "REJECTED"
            self._reason = str(error)
            raise ValueError("Sweep completion failed: " + str(error)) from error

    def finish(self) -> VerifiedTerrainPair:
        if self._result is None:
            if self._state != "REJECTED":
                self.abort("Incomplete pair")
            raise ValueError("No accepted pair: " + str(self._reason))
        return self._result
