"""Bounded deterministic Dijkstra for loopless construction geometry, never vehicle routing."""

import heapq
from dataclasses import dataclass
from decimal import Decimal

from app.planning.preparation.candidates import FacilitySite, adjacent, eligible
from app.planning.preparation.domain import ExtractedWorldSnapshot, PreparationRequest
from app.planning.preparation.failures import PreparationFailureCode as Code
from app.planning.preparation.failures import fail


@dataclass
class SearchBudget:
    expansions: int = 0


def search_corridors(
    world: ExtractedWorldSnapshot,
    request: PreparationRequest,
    origin: FacilitySite,
    destination: FacilitySite,
    anchor: int,
    reserved: frozenset[int],
    budget: SearchBudget,
) -> tuple[tuple[int, ...], ...]:
    """Dijkstra labels retain visited sets: waypoint paths cannot safely merge histories.

    The geometry state is (tile, incoming direction). Anchor progress and visited
    tiles distinguish labels, preventing a cheaper dead-end history from hiding a
    feasible loopless anchor path. Bound label count as well as expansions.
    """
    source = world.prepared_save_digest
    tiles = {t.tile_index: t for t in world.tiles}
    endpoints = {origin.tile_index, destination.tile_index}
    allowed = {i for i, t in tiles.items() if eligible(t) and (i not in reserved or i in endpoints)}
    for index in (*endpoints, origin.front_tile, destination.front_tile, anchor):
        if index not in allowed:
            fail(
                Code.UNSUPPORTED_TERRAIN,
                "corridors",
                source,
                "corridor endpoint/front/anchor is not eligible",
                str(index),
            )
    if origin.tile_index == destination.tile_index:
        fail(Code.NO_FEASIBLE_CORRIDOR, "corridors", source, "station footprints coincide")
    # Fixed-point conversion is exact; no binary floating point or rounded money.
    cost = world.road_build_cost_gbp
    exponent = cost.as_tuple().exponent
    assert isinstance(exponent, int)
    scale = 10 ** max(0, -exponent)
    unit_cost = int(cost * Decimal(scale))
    start = (origin.tile_index, origin.front_tile)
    if tiles[start[0]].height != tiles[start[1]].height:
        fail(Code.UNSUPPORTED_TERRAIN, "corridors", source, "station front height differs")
    initial_direction = origin.orientation
    queue: list[tuple[int, int, int, tuple[int, ...], str, bool]] = [
        (unit_cost * 2, 2, 0, start, initial_direction, anchor in start)
    ]
    # Identical visited sets can merge; differing sets can have different legal futures.
    seen: dict[tuple[int, str, bool, frozenset[int]], int] = {}
    generated = 1
    result = []
    length_pruned = False
    while queue:
        money, length, turns, path, incoming, anchored = heapq.heappop(queue)
        key = (path[-1], incoming, anchored, frozenset(path))
        if seen.get(key, 0) >= request.limits.corridors_per_pair:
            continue
        seen[key] = seen.get(key, 0) + 1
        budget.expansions += 1
        if budget.expansions > request.limits.aggregate_expansions:
            fail(
                Code.CANDIDATE_LIMIT_EXCEEDED,
                "corridors",
                source,
                "aggregate search expansions exceed policy bound",
            )
        if len(seen) > request.limits.search_states_per_pair:
            fail(
                Code.CANDIDATE_LIMIT_EXCEEDED,
                "corridors",
                source,
                "station pair search states exceed policy bound",
            )
        if path[-1] == destination.tile_index:
            if anchored:
                result.append(path)
                if len(result) == request.limits.corridors_per_pair:
                    return tuple(result)
            continue
        for direction, index in adjacent(world, path[-1]):
            if index not in allowed or index in path:
                continue
            if index == destination.tile_index and path[-1] != destination.front_tile:
                continue
            if index == origin.tile_index or tiles[index].height != tiles[path[-1]].height:
                continue
            if length >= request.limits.corridor_length:
                length_pruned = True
                continue
            candidate = path + (index,)
            generated += 1
            if generated > request.limits.search_states_per_pair:
                fail(
                    Code.CANDIDATE_LIMIT_EXCEEDED,
                    "corridors",
                    source,
                    "station pair generated labels exceed policy bound",
                )
            heapq.heappush(
                queue,
                (
                    money + unit_cost,
                    length + 1,
                    turns + (direction != incoming),
                    candidate,
                    direction,
                    anchored or index == anchor,
                ),
            )
    if length_pruned:
        fail(
            Code.CANDIDATE_LIMIT_EXCEEDED,
            "corridors",
            source,
            "corridor length bound prevented complete search",
        )
    if not result:
        fail(
            Code.NO_FEASIBLE_CORRIDOR,
            "corridors",
            source,
            "supported loopless anchor search space exhausted",
        )
    return tuple(result)
