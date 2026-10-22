"""Bounded terrain-modification planning for P08 (OpenTTD 15.3 GSTile verified).

Offline planning/validation contracts only: **native execution stays unsupported
until separately validated** by a reviewed one-shot run (see the module notes on
the verified command surface). Proposals are diagnostics attached to bounded
P08 outcomes; they never enter an executable ExecutionPlan as construction
actions and never make a skipped P05 milestone succeed.

Verified official OpenTTD 15.3 source facts (``src/script/api/script_tile.hpp``
and ``script_tile.cpp`` at tag 15.3):

- ``GSTile.RaiseTile(tile, slope)`` / ``GSTile.LowerTile(tile, slope)`` issue
  ``CMD_TERRAFORM_LAND`` with an explicit corner bit mask, ``GSCompanyMode``
  required, corners processed west, south, east, north; one corner can cascade
  others; errors ``ERR_AREA_NOT_CLEAR``, ``ERR_TOO_CLOSE_TO_EDGE``,
  ``ERR_TILE_TOO_HIGH`` / ``ERR_TILE_TOO_LOW`` (plus terraform-limit-derived
  ``ERR_LIMIT_REACHED`` in the command layer). Per-corner costs bill through
  ``GetBuildCost(BT_TERRAFORM)`` only at runtime - never invented offline.
- ``GSTile.LevelTiles(start, end)`` issues ``CMD_LEVEL_LAND`` and is explicitly
  prohibited in proposals: it may partially apply on failure and may return
  true in ``ScriptTestMode`` while failing in ``ScriptExecMode``.
- ``GSTile.DemolishTile(tile)`` issues ``CMD_LANDSCAPE_CLEAR`` from deity or
  company mode; used only as the classified clearing prerequisite.
- ``GSTile.GetCornerHeight`` / ``GetMinHeight`` / ``GetSlope`` are the mandatory
  post-operation readbacks.

Corner-height derivation from retained ``TileFact`` uses the official slope
bit encoding (``src/slope_type.h``): west=1, south=2, east=4, north=8,
steep flag 16. The named corner of tile (x, y) maps to map points
N=(x, y), E=(x, y+1), W=(x+1, y), S=(x+1, y+1); this mapping was verified
against the retained Seed 17 native capture (zero shared-corner
contradictions across the whole captured world).
"""

import heapq
import json
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import Literal

from app.planning.p08_adapter import MAX_PATH_EXPANSIONS
from app.simulation.openttd.supplemental_planning_facts import SupplementalPlanningFacts, TileFact
from app.simulation.openttd.tile_classification import projection_disagrees

PROPOSAL_VERSION = "terrain-proposal-v1"
# Operational-analytics extension point: terrain modification CAPEX can later be
# attributed to this category separately from transport-infrastructure CAPEX once
# a native attempt supplies GSTile.GetBuildCost(BT_TERRAFORM) spend observations.
CAPEX_CATEGORY_TERRAIN = "terrain-modification"
CAPEX_CATEGORY_INFRASTRUCTURE = "transport-infrastructure"

# Official src/slope_type.h slope bits (no halftile encodings: TileFact caps at 31).
SLOPE_W = 0x1
SLOPE_S = 0x2
SLOPE_E = 0x4
SLOPE_N = 0x8
SLOPE_STEEP = 0x10
SLOPE_HALFTILE_MIN = 0x20
CORNER_NAMES = ("N", "E", "W", "S")
CORNER_BITS = {"N": SLOPE_N, "E": SLOPE_E, "W": SLOPE_W, "S": SLOPE_S}
# Verified named-corner -> shared map point offsets for a tile at (x, y).
CORNER_POINT_OFFSET = {"N": (0, 0), "E": (0, 1), "W": (1, 0), "S": (1, 1)}
OPPOSITE_CORNER = {"N": "S", "S": "N", "E": "W", "W": "E"}

# Proposal budgets (planning side; native terraform-limit settings apply on top
# and remain unknown offline).
MAX_TERRAIN_CORNER_OPS = 32
MAX_TERRAIN_HEIGHT_DELTA_STEPS = 1
MAX_TERRAIN_CLEARED_TILES = 8
MAX_TERRAIN_REGION_TILES = 128
# The native admission keeps road paths 2..47 tiles, so a proposal must leave
# that bound reachable: interior road tiles stay <= 47.
MAX_TERRAIN_CORRIDOR_INTERIOR = 47
DIRECTIONS = ((0, -1), (1, 0), (0, 1), (-1, 0))


class TerrainInfeasibilityCode:
    """Structured offline validation outcomes; no native mutation is implied."""

    UNSUPPORTED_SLOPE_ENCODING = "UNSUPPORTED_SLOPE_ENCODING"
    NO_CONNECTED_LEVELED_CORRIDOR = "NO_CONNECTED_LEVELED_CORRIDOR"
    SEARCH_LIMIT_EXCEEDED = "SEARCH_LIMIT_EXCEEDED"
    FORBIDDEN_TILE_IN_REGION = "FORBIDDEN_TILE_IN_REGION"
    UNOBSERVED_TILE_AFFECTED = "UNOBSERVED_TILE_AFFECTED"
    TERRAIN_BUDGET_EXCEEDED = "TERRAIN_BUDGET_EXCEEDED"


@dataclass(frozen=True)
class TerrainOp:
    """One classified terrain operation over a verified 15.3 command seam.

    ``raise``/``lower`` carry exactly one height step for each listed corner of
    ``tile_id`` (mapped to ``GSTile.RaiseTile``/``LowerTile`` with the matching
    corner mask, one step per corner); ``clear`` lets the executor demolish the
    tile first (``GSTile.DemolishTile``). Shared corner points are written
    through a single host entry, so the same point is never modified twice.
    """

    kind: Literal["raise", "lower", "clear"]
    tile_id: int
    corners: tuple[str, ...]  # CORNER_NAMES subset for raise/lower; empty for clear
    before_height: int
    target_height: int

    @property
    def sort_key(self) -> tuple:
        return (self.tile_id, self.kind, self.corners)


@dataclass(frozen=True)
class TerrainProposal:
    """Planning-only levelling proposal; never an executable plan."""

    corridor: tuple[int, ...]
    interior_road_tiles: int
    target_height: int
    pickup_stop: int
    delivery_stop: int
    region_tiles: tuple[int, ...]
    halo_tiles: tuple[int, ...]
    ops: tuple[TerrainOp, ...]
    cleared_tiles: tuple[int, ...]
    search_expansions: int
    height_delta_steps: int = MAX_TERRAIN_HEIGHT_DELTA_STEPS
    version: str = PROPOSAL_VERSION
    execution_status: Literal["PLANNING_ONLY"] = "PLANNING_ONLY"
    native_execution: Literal["UNSUPPORTED_PENDING_SEPARATE_VALIDATION"] = (
        "UNSUPPORTED_PENDING_SEPARATE_VALIDATION"
    )
    cost_category: str = CAPEX_CATEGORY_TERRAIN
    # Native terraform spend is never derived offline; it requires a separately
    # authorized capture of GSTile.GetBuildCost(BT_TERRAFORM) plus command logs
    # and then belongs to CAPEX_CATEGORY_TERRAIN, distinct from infrastructure.
    terraform_cost_gbp: None = None
    required_readbacks: tuple[str, ...] = (
        "GSTile.GetSlope",
        "GSTile.GetMinHeight",
        "GSTile.GetCornerHeight",
        "GSTile.GetCargoAcceptance",
        "GSTile.GetCargoProduction",
    )

    @property
    def digest(self) -> str:
        payload = {
            "version": self.version,
            "execution_status": self.execution_status,
            "native_execution": self.native_execution,
            "corridor": list(self.corridor),
            "target_height": self.target_height,
            "stops": [self.pickup_stop, self.delivery_stop],
            "region": list(self.region_tiles),
            "halo": list(self.halo_tiles),
            "ops": [
                [op.kind, op.tile_id, list(op.corners), op.before_height, op.target_height]
                for op in self.ops
            ],
            "cleared": list(self.cleared_tiles),
            "cost_category": self.cost_category,
        }
        return sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


@dataclass(frozen=True)
class TerrainInfeasibility:
    """Structured planner rejection with the exact offline justification."""

    code: str
    detail: str
    search_expansions: int = 0


TerrainOutcome = TerrainProposal | TerrainInfeasibility

Point = tuple[int, int]


def corner_heights(tile: TileFact) -> dict[str, int]:
    """Derive the four corner heights of a captured tile from official bits."""
    base = tile.min_height
    slope = tile.slope
    if slope == 0:
        return {name: base for name in CORNER_NAMES}
    if slope & SLOPE_HALFTILE_MIN:
        raise ValueError("halftile slope encodings are outside the retained fact contract")
    if slope & SLOPE_STEEP:
        mask = slope & (SLOPE_N | SLOPE_E | SLOPE_W | SLOPE_S)
        unmasked = next(name for name in CORNER_NAMES if not CORNER_BITS[name] & mask)
        opposite = OPPOSITE_CORNER[unmasked]
        return {
            name: base + 2 if name == opposite else (base + 1 if CORNER_BITS[name] & mask else base)
            for name in CORNER_NAMES
        }
    return {name: base + (1 if CORNER_BITS[name] & slope else 0) for name in CORNER_NAMES}


def _requires_clearing(tile: TileFact) -> bool:
    """Classified clearing prerequisites; bare land shapes need none."""
    return any((tile.tree, tile.rough, tile.rock, tile.farm))


def _region_forbidden(tile: TileFact) -> bool:
    """Mutation must not touch water/coast, industry, existing transport, or
    tiles whose native obstruction class was not captured (houses/stations:
    the retained TileFact projection drops those flags, so their clearing
    semantics cannot be classified offline)."""
    return any(
        (
            tile.water,
            tile.coast,
            tile.industry_id is not None,
            tile.road,
            tile.rail,
            tile.water_transport,
            tile.air_transport,
            not tile.buildable,
        )
    )


def _corridor_class(tile: TileFact) -> Literal["clean", "clearing", "forbidden"]:
    if _region_forbidden(tile):
        return "forbidden"
    if _requires_clearing(tile):
        # Obstructed land (trees, rough, rocks, fields) is road-hostable only
        # after a classified clearing: GSTile.DemolishTile first, then corner
        # corrections against the observed slope, then a fresh native readback.
        return "clearing"
    if not tile.buildable:
        # Retained facts project native house/station flags away, so a tile
        # that is neither buildable nor classified clearable carries an
        # unclassifiable obstruction: reject instead of guessing its class.
        return "forbidden"
    return "clean"


def _cardinals(tile: TileFact, by_id: dict[int, TileFact], width: int):
    for dx, dy in DIRECTIONS:
        n = by_id.get((tile.y + dy) * width + tile.x + dx)
        if n is not None and (n.x, n.y) == (tile.x + dx, tile.y + dy):
            yield n


def _shared_points(tile: TileFact) -> dict[Point, str]:
    return {(tile.x + dx, tile.y + dy): name for name, (dx, dy) in CORNER_POINT_OFFSET.items()}


def plan_bounded_levelling(
    facts: SupplementalPlanningFacts,
    eligible_pickups: tuple[int, ...],
    eligible_deliveries: tuple[int, ...],
    *,
    budget: int = MAX_PATH_EXPANSIONS,
    corner_ops_limit: int = MAX_TERRAIN_CORNER_OPS,
    cleared_tiles_limit: int = MAX_TERRAIN_CLEARED_TILES,
    region_tiles_limit: int = MAX_TERRAIN_REGION_TILES,
) -> TerrainOutcome:
    """Search the smallest deterministic levelling proposal joining the stops.

    For each candidate flat target height, one bounded shared-super-source
    Dijkstra runs twice (outermost captured ring permitted, then ring excluded)
    over terrain-classified tiles reachable inside
    ``MAX_TERRAIN_HEIGHT_DELTA_STEPS``; each pass yields one canonical candidate
    per connected delivery stop; every candidate is validated under
    shared-corner region closure. Invalid candidates are rejected with
    structured codes, and the best valid candidate wins lexicographically by
    (corner ops, clearings, hops, target height, corridor identity). Returns
    :class:`TerrainProposal` (planning-only, native execution unsupported) or
    :class:`TerrainInfeasibility`. ``facts`` may be retained evidence: only the
    captured map size and tiles are read.
    """
    if not eligible_pickups or not eligible_deliveries:
        return TerrainInfeasibility(
            TerrainInfeasibilityCode.NO_CONNECTED_LEVELED_CORRIDOR,
            "both eligible stop sets are required",
        )
    facts_tiles = {t.tile_id: t for t in facts.tiles}
    if not set(eligible_pickups) <= set(facts_tiles) or not set(eligible_deliveries) <= set(
        facts_tiles
    ):
        return TerrainInfeasibility(
            TerrainInfeasibilityCode.NO_CONNECTED_LEVELED_CORRIDOR,
            "eligible stops outside captured facts",
        )
    try:
        for tile in facts_tiles.values():
            _ = corner_heights(tile)
    except ValueError:
        return TerrainInfeasibility(
            TerrainInfeasibilityCode.UNSUPPORTED_SLOPE_ENCODING,
            "captured slope encodings cannot express corner heights",
        )
    width = facts.source.map_width
    map_height = facts.source.map_height
    corridor_classes = {t.tile_id: _corridor_class(t) for t in facts.tiles}
    targets = sorted(
        set(facts_tiles[i].min_height for i in (*eligible_pickups, *eligible_deliveries))
    )
    best: tuple | None = None
    expansions_used = 0
    rejections: dict[str, int] = {}
    for target in targets:
        base = {
            tile_id: tile
            for tile_id, tile in facts_tiles.items()
            if corridor_classes[tile_id] in ("clean", "clearing")
            and all(
                0 <= target - height <= MAX_TERRAIN_HEIGHT_DELTA_STEPS
                for height in corner_heights(tile).values()
            )
        }
        # Two bounded search passes. Pass one permits the outermost captured
        # ring; if its tree candidates all fail validation (e.g. corner
        # closures touching unobserved map tiles), pass two repeats the search
        # with the ring excluded so interior corridors are still enumerated.
        # Both passes are fully validated; the best valid candidate wins.
        ring = {
            tile_id
            for tile_id, tile in facts_tiles.items()
            if min(
                tile.x - facts.region.x,
                facts.region.x + facts.region.width - 1 - tile.x,
                tile.y - facts.region.y,
                facts.region.y + facts.region.height - 1 - tile.y,
            )
            == 0
        }
        ring_free = {tile_id: tile for tile_id, tile in base.items() if tile_id not in ring}
        for hostable in (base, ring_free):
            remaining = max(0, budget - expansions_used)
            reached, expansions = _levelling_search(
                eligible_pickups, eligible_deliveries, hostable, facts_tiles, width, remaining
            )
            expansions_used += expansions
            if not reached:
                continue  # budget-exhausted or no target-joined candidate
            for goal, corridor in sorted(reached.items()):
                if len(corridor) < 3 or len(corridor) - 2 > MAX_TERRAIN_CORRIDOR_INTERIOR:
                    continue
                evaluation = _evaluate_candidate(
                    corridor,
                    target,
                    facts_tiles,
                    width,
                    map_height,
                    eligible_pickups,
                    eligible_deliveries,
                )
                if isinstance(evaluation, TerrainInfeasibility):
                    rejections[evaluation.code] = rejections.get(evaluation.code, 0) + 1
                    continue
                candidate_key = (
                    evaluation["ops_count"],
                    evaluation["closings"],
                    len(corridor),
                    target,
                    corridor,
                )
                if best is None or candidate_key < best[0]:
                    best = (candidate_key, corridor, target, evaluation)
    if best is None:
        code = TerrainInfeasibilityCode.NO_CONNECTED_LEVELED_CORRIDOR
        if rejections and set(rejections) == {TerrainInfeasibilityCode.UNOBSERVED_TILE_AFFECTED}:
            code = TerrainInfeasibilityCode.UNOBSERVED_TILE_AFFECTED
        elif rejections and set(rejections) == {TerrainInfeasibilityCode.FORBIDDEN_TILE_IN_REGION}:
            code = TerrainInfeasibilityCode.FORBIDDEN_TILE_IN_REGION
        breakdown = "; ".join(f"{kind}x{count}" for kind, count in sorted(rejections.items()))
        detail = "no bounded levelling proposal connects the eligible stops"
        if breakdown:
            detail += f" (rejected candidates: {breakdown})"
        if not breakdown and expansions_used >= budget:
            code = TerrainInfeasibilityCode.SEARCH_LIMIT_EXCEEDED
        return TerrainInfeasibility(
            code,
            detail,
            search_expansions=expansions_used,
        )
    _, corridor, target, evaluation = best
    proposal = _compose_proposal(corridor, target, evaluation, facts_tiles, expansions_used)
    if len([op for op in proposal.ops if op.kind in ("raise", "lower")]) > corner_ops_limit:
        return TerrainInfeasibility(
            TerrainInfeasibilityCode.TERRAIN_BUDGET_EXCEEDED,
            f"corner operations exceed {corner_ops_limit}",
            search_expansions=expansions_used,
        )
    if len(proposal.cleared_tiles) > cleared_tiles_limit:
        return TerrainInfeasibility(
            TerrainInfeasibilityCode.TERRAIN_BUDGET_EXCEEDED,
            f"cleared tiles {len(proposal.cleared_tiles)} exceed {cleared_tiles_limit}",
            search_expansions=expansions_used,
        )
    if len(proposal.region_tiles) > region_tiles_limit:
        return TerrainInfeasibility(
            TerrainInfeasibilityCode.TERRAIN_BUDGET_EXCEEDED,
            f"region tiles {len(proposal.region_tiles)} exceed {region_tiles_limit}",
            search_expansions=expansions_used,
        )
    return proposal


def _levelling_search(
    pickups: tuple[int, ...],
    deliveries: tuple[int, ...],
    hostable: dict[int, TileFact],
    facts_tiles: dict[int, TileFact],
    width: int,
    budget: int,
) -> tuple[dict[int, tuple[int, ...]] | None, int]:
    """Bounded shared-source search for corridors hostable at one target height.

    Returns deterministic per-delivery parent-tree corridors, or ``None`` when
    the budget is exhausted; empty mapping means no target-joined candidate.
    """
    if not hostable or budget <= 0 or not set(pickups) <= set(hostable):
        return {}, 0
    best = {p: 0 for p in pickups}
    parents: dict[int, int | None] = {p: None for p in best}
    pending = [(cost, tile) for tile, cost in best.items()]
    heapq.heapify(pending)
    settled: set[int] = set()
    expansions = 0
    while pending:
        if expansions >= budget:
            return None, expansions
        cost, i = heapq.heappop(pending)
        if i in settled:
            continue
        settled.add(i)
        expansions += 1
        for n in _cardinals(facts_tiles[i], facts_tiles, width):
            if n.tile_id not in hostable:
                continue
            if n.tile_id not in best or cost + 1 < best[n.tile_id]:
                best[n.tile_id] = cost + 1
                parents[n.tile_id] = i
                heapq.heappush(pending, (cost + 1, n.tile_id))
    reached: dict[int, tuple[int, ...]] = {}
    for goal in deliveries:
        if goal not in best or best[goal] == 0 and goal not in pickups:
            continue
        path = [goal]
        while parents[path[-1]] is not None:
            parent = parents[path[-1]]
            assert parent is not None
            path.append(parent)
        reached[goal] = tuple(reversed(path))
    return reached, expansions


def _halo(tiles: tuple[int, ...], facts_tiles: dict[int, TileFact], width: int):
    seen = set(tiles)
    for tile_id in tiles:
        for n in _cardinals(facts_tiles[tile_id], facts_tiles, width):
            if n.tile_id not in seen:
                seen.add(n.tile_id)
    return set(seen)


def _evaluate_candidate(
    corridor: tuple[int, ...],
    target: int,
    facts_tiles: dict[int, TileFact],
    width: int,
    map_height: int,
    eligible_pickups: tuple[int, ...],
    eligible_deliveries: tuple[int, ...],
) -> dict | TerrainInfeasibility:
    """Validate a candidate corridor at ``target`` under shared-corner closure."""
    if corridor[0] not in eligible_pickups or corridor[-1] not in eligible_deliveries:
        return TerrainInfeasibility(
            TerrainInfeasibilityCode.NO_CONNECTED_LEVELED_CORRIDOR,
            "candidate corridor does not join eligible stops",
        )
    adjustments: dict[Point, int] = {}
    for tile_id in corridor:
        tile = facts_tiles[tile_id]
        for name, height in corner_heights(tile).items():
            if height != target:
                point = next(p for p, n in _shared_points(tile).items() if n == name)
                adjustments.setdefault(point, height)
    # Region closure: every captured tile sharing an adjusted corner joins the
    # region; a map grid tile sharing a corner while missing from the capture
    # stays unobserved and must reject the proposal (no corner writes off-capture).
    region = set(corridor)
    for point in adjustments:
        px, py = point
        for dx, dy in ((0, 0), (-1, 0), (0, -1), (-1, -1)):
            x, y = px + dx, py + dy
            if not 0 <= x < width or not 0 <= y < map_height:
                continue  # outside the map grid: no world tile exists
            tile = facts_tiles.get(y * width + x)
            if tile is None or (tile.x, tile.y) != (x, y):
                return TerrainInfeasibility(
                    TerrainInfeasibilityCode.UNOBSERVED_TILE_AFFECTED,
                    f"corner point {point} is shared with unobserved tile ({x},{y})",
                )
            region.add(tile.tile_id)
    for tile_id in region:
        tile = facts_tiles[tile_id]
        if _region_forbidden(tile):
            return TerrainInfeasibility(
                TerrainInfeasibilityCode.FORBIDDEN_TILE_IN_REGION,
                f"region tile ({tile.x},{tile.y}) may not be modified",
            )
    halo_set = _halo(tuple(sorted(region)), facts_tiles, width)
    halo = tuple(sorted(halo_set - region))
    # Every region tile with classified obstructed ground must be cleared
    # (DemolishTile) before corner writes: rim trees/rough/rocks/fields share
    # adjusted corners exactly like corridor tiles do.
    cleared = tuple(sorted(tid for tid in region if _requires_clearing(facts_tiles[tid])))
    ops, ops_count = _group_ops(adjustments, region, facts_tiles, width, map_height, target)
    return {
        "ops_count": ops_count,
        "ops": ops,
        "closings": len(cleared),
        "region": region,
        "halo": halo,
        "cleared": cleared,
    }


def _group_ops(
    adjustments: dict[Point, int],
    region: set[int],
    facts_tiles: dict[int, TileFact],
    width: int,
    map_height: int,
    target: int,
) -> tuple[tuple[TerrainOp, ...], int]:
    """Group corner adjustments into deterministic per-tile raise/lower ops.

    Each adjusted shared point is written exactly once, hosted on the smallest
    captured tile id sharing it. Deterministic order: host tile id, then kind,
    then corner names. All adjustments move exactly one height step; a host may
    carry both a raise group and a lower group (separate ops).
    """
    corner_groups: dict[tuple[int, Literal["raise", "lower"]], list[str]] = {}
    for point, before in adjustments.items():
        kind: Literal["raise", "lower"] = "raise" if before < target else "lower"
        hosts = []
        for dx, dy in ((0, 0), (-1, 0), (0, -1), (-1, -1)):
            x, y = point[0] + dx, point[1] + dy
            tile = facts_tiles.get(y * width + x)
            if (
                tile is not None
                and 0 <= x < width
                and 0 <= y < map_height
                and (tile.x, tile.y) == (x, y)
                and tile.tile_id in region
            ):
                hosts.append(tile.tile_id)
        if not hosts:  # pragma: no cover - closure guarantees region hosts
            return (), 0
        tile = facts_tiles[min(hosts)]
        name = next(
            n for n, (dx, dy) in CORNER_POINT_OFFSET.items() if (tile.x + dx, tile.y + dy) == point
        )
        corner_groups.setdefault((min(hosts), kind), []).append(name)
    ops: list[TerrainOp] = []
    for (host, kind), corners in sorted(
        corner_groups.items(), key=lambda item: (item[0][0], item[0][1])
    ):
        ordered = tuple(name for name in CORNER_NAMES if name in corners)
        delta = 1 if kind == "raise" else -1
        ops.append(TerrainOp(kind, host, ordered, target - delta, target))
    return tuple(ops), len(ops)


def _compose_proposal(
    corridor: tuple[int, ...],
    target: int,
    evaluation: dict,
    facts_tiles: dict[int, TileFact],
    expansions: int,
) -> TerrainProposal:
    """Deterministic :class:`TerrainProposal` from a validated candidate."""
    cleared = tuple(sorted(evaluation["cleared"]))
    clear_ops = tuple(
        TerrainOp("clear", tile_id, (), facts_tiles[tile_id].min_height, target)
        for tile_id in cleared
    )
    ops = tuple(sorted(evaluation["ops"] + clear_ops, key=lambda op: op.sort_key))
    corridor = tuple(corridor)
    region = tuple(sorted(evaluation["region"]))
    return TerrainProposal(
        corridor=corridor,
        interior_road_tiles=len(corridor) - 2,
        target_height=target,
        pickup_stop=corridor[0],
        delivery_stop=corridor[-1],
        region_tiles=region,
        halo_tiles=evaluation["halo"],
        ops=ops,
        cleared_tiles=cleared,
        search_expansions=expansions,
    )


FEASIBILITY_VERSION = "feasibility-diagnosis-v1"


class SegmentClass(StrEnum):
    """Per-tile corridor feasibility under bounded, offline-verifiable rules.

    Classification answers only "what construction operations would a road
    here require"; it is never construction authority and never implies native
    success.
    """

    ROAD_BUILDABLE = "ROAD_BUILDABLE"
    SUPPORTED_CLEARING = "SUPPORTED_CLEARING"
    TERRAIN_MODIFICATION = "TERRAIN_MODIFICATION"
    UNSUPPORTED_CONSTRUCTION = "UNSUPPORTED_CONSTRUCTION"
    UNKNOWN_OCCUPANCY = "UNKNOWN_OCCUPANCY"


SUPPORTED_SEGMENT_CLASSES = (
    SegmentClass.ROAD_BUILDABLE,
    SegmentClass.SUPPORTED_CLEARING,
    SegmentClass.TERRAIN_MODIFICATION,
)


class FeasibilityCode:
    """Stable world-feasibility diagnostic codes for Task D.

    Externally consumed P08 codes (``NO_BOUNDED_CORRIDOR``,
    ``NO_CONNECTED_LEVELED_CORRIDOR``, ``SEARCH_LIMIT_EXCEEDED``) are not
    renamed; these are additive assessment codes consumed by diagnostics
    output and tests.
    """

    NO_CONNECTED_CORRIDOR = "NO_CONNECTED_CORRIDOR"
    TERRAIN_MODIFICATION_REQUIRED = "TERRAIN_MODIFICATION_REQUIRED"
    UNSUPPORTED_CONSTRUCTION = "UNSUPPORTED_CONSTRUCTION"
    INCOMPLETE_TILE_CLASSIFICATION = "INCOMPLETE_TILE_CLASSIFICATION"
    SEARCH_BUDGET_EXCEEDED = "SEARCH_BUDGET_EXCEEDED"
    CONNECTED_WITHOUT_MODIFICATION = "CONNECTED_WITHOUT_MODIFICATION"


# Occupancy classification (schema-2 TileClass values) -> corridor segment
# class. Everything above ground/obstruction level is unsupported construction
# offline because the corresponding conversion permissions (station demo,
# house clearance and its town rating, dock/airport/rail/road removal) are not
# verifiable from retained bytes.
_OCCUPANCY_SEGMENT: dict[str, SegmentClass] = {
    "HOUSE": SegmentClass.UNSUPPORTED_CONSTRUCTION,
    "STATION": SegmentClass.UNSUPPORTED_CONSTRUCTION,
    "INDUSTRY": SegmentClass.UNSUPPORTED_CONSTRUCTION,
    "WATER": SegmentClass.UNSUPPORTED_CONSTRUCTION,
    "COAST": SegmentClass.UNSUPPORTED_CONSTRUCTION,
    "AIRPORT": SegmentClass.UNSUPPORTED_CONSTRUCTION,
    "ROAD": SegmentClass.UNSUPPORTED_CONSTRUCTION,
    "RAIL": SegmentClass.UNSUPPORTED_CONSTRUCTION,
    "DOCK": SegmentClass.UNSUPPORTED_CONSTRUCTION,
    "TREES": SegmentClass.SUPPORTED_CLEARING,
    "FARM": SegmentClass.SUPPORTED_CLEARING,
    "ROCK": SegmentClass.SUPPORTED_CLEARING,
    "ROUGH": SegmentClass.SUPPORTED_CLEARING,
    "CLEAR": SegmentClass.SUPPORTED_CLEARING,  # refined by legacy slope below
    "UNKNOWN_OCCUPANCY": SegmentClass.UNKNOWN_OCCUPANCY,
}


def _projection_disagrees(tile: TileFact, flags: int) -> bool:
    """Exact compare of schema-2 flag bits against the TileFact projection.

    Single source of truth lives in the simulation wire layer
    (``tile_classification.projection_disagrees``); the road-OR, the carried
    ground/transport bits and the buildable/house/station suppression there
    are the exact projection-coherence gate this assessor reuses.
    """
    return projection_disagrees(tile, flags)


def _legacy_segment(tile: TileFact) -> tuple[SegmentClass, str]:
    """Classification from the legacy TileFact projection alone."""
    if any(
        (
            tile.water,
            tile.coast,
            tile.road,
            tile.rail,
            tile.water_transport,
            tile.air_transport,
            tile.industry_id is not None,
        )
    ):
        return (SegmentClass.UNSUPPORTED_CONSTRUCTION, "projected-native-footprint")
    if any((tile.tree, tile.farm, tile.rock, tile.rough)):
        return (SegmentClass.SUPPORTED_CLEARING, "projected-clearing-ground")
    if not tile.buildable:
        return (SegmentClass.UNKNOWN_OCCUPANCY, "projection-dropped-occupancy-class")
    if tile.slope == 0:
        return (SegmentClass.ROAD_BUILDABLE, "vacant-flat-clear")
    return (SegmentClass.TERRAIN_MODIFICATION, "cleared-shape-needs-corner-correction")


def classify_segment(
    tile: TileFact,
    tile_class: str | None = None,
    *,
    flags: int | None = None,
) -> tuple[SegmentClass, str]:
    """Classify one captured tile for corridor feasibility.

    ``tile_class`` is a schema-2 :class:`TileClass` value (or ``None`` when no
    classification evidence exists). Rules, in order:

    - No classification evidence: the legacy projection decides; tiles whose
      occupancy class it dropped stay ``UNKNOWN_OCCUPANCY`` (never inferred).
    - House/station/industry/transport occupancy: ``UNSUPPORTED_CONSTRUCTION``
      (conversion permissions unverified offline).
    - Trees/farm/rock/rough: ``SUPPORTED_CLEARING`` (classified DemolishTile).
    - Clear ground: follows the legacy shape - flat is ``ROAD_BUILDABLE``,
      sloped is ``TERRAIN_MODIFICATION``; but a CLEAR classification over
      projected clearing ground is also a contradiction (same-instant facts
      cannot differ about a felled tree): it downgrades to
      ``UNKNOWN_OCCUPANCY``.
    - Contradictions between schema-2 classification and legacy facts (e.g.
      CLEAR ground over a projected water tile) downgrade to
      ``UNKNOWN_OCCUPANCY``: fail explicit instead of arbitrating between
      inconsistent observations.
    """
    legacy, legacy_reason = _legacy_segment(tile)
    if tile_class is None and flags is None:
        return (legacy, legacy_reason)
    if flags is not None and _projection_disagrees(tile, flags):
        # Shared native predicates must project identically in the same
        # capture instant; any disagreement is evidence-theft prevention,
        # not a refutation of either observation alone.
        return (SegmentClass.UNKNOWN_OCCUPANCY, "conflicting-occupancy-evidence")
    if tile_class is None:
        return (legacy, legacy_reason)
    mapped = _OCCUPANCY_SEGMENT.get(tile_class)
    if mapped is None:
        return (SegmentClass.UNKNOWN_OCCUPANCY, "unrecognized-classification-value")
    if mapped is SegmentClass.UNKNOWN_OCCUPANCY:
        return (SegmentClass.UNKNOWN_OCCUPANCY, "no-classifying-predicate")
    if mapped is not SegmentClass.UNSUPPORTED_CONSTRUCTION and legacy in (
        SegmentClass.UNSUPPORTED_CONSTRUCTION,
    ):
        # A ground claim cannot override an observed native footprint in the
        # same capture instant.
        return (SegmentClass.UNKNOWN_OCCUPANCY, "conflicting-occupancy-evidence")
    if (
        flags is None
        and legacy is SegmentClass.SUPPORTED_CLEARING
        and mapped is not SegmentClass.UNSUPPORTED_CONSTRUCTION
    ):
        # An index-only class (no same-instant mask) over projected clearing
        # ground cannot prove it captured the same instant: the felled-tree
        # ambiguity is refused explicitly. With a coherent mask the shared
        # ground bits above were already verified, so an agreeing TREES/
        # FARM/ROCK/ROUGH claim is the same observation, not a contradiction
        # (and CLEAR ground over tree facts cannot pass the mask either).
        return (SegmentClass.UNKNOWN_OCCUPANCY, "conflicting-occupancy-evidence")
    if mapped is SegmentClass.UNSUPPORTED_CONSTRUCTION:
        return (mapped, f"classified-occupancy:{tile_class}")
    if mapped is SegmentClass.SUPPORTED_CLEARING and tile_class != "CLEAR":
        return (mapped, f"classified-clearing:{tile_class}")
    if tile_class == "CLEAR":
        if not tile.buildable:
            return (SegmentClass.UNKNOWN_OCCUPANCY, "conflicting-occupancy-evidence")
        if tile.slope == 0:
            return (SegmentClass.ROAD_BUILDABLE, "classified-clear-flat")
        return (SegmentClass.TERRAIN_MODIFICATION, "classified-clear-sloped")
    raise AssertionError("unreachable classification branch")


@dataclass(frozen=True)
class FeasibilityDiagnosis:
    """Bounded world-feasibility record; JSON-ready; no native claim.

    Records world identity, assessed industry relationship, observed tile
    coverage, per-class corridor results, the required construction-operation
    inventory and exact rejection reasons. ``required_ops`` are tile-level
    requirements only; the actual grouped operations (and any execution intent)
    come from :func:`plan_bounded_levelling` and stay planning-only.
    """

    world_id: str
    map_width: int
    map_height: int
    region: tuple[int, int, int, int]
    relationship: tuple[tuple[str, int, int], ...]
    observed_tiles: int
    pickups: int
    deliveries: int
    segment_counts: tuple[tuple[str, int], ...]
    code: str
    detail: str
    corridor: tuple[int, ...] = ()
    corridor_segment_counts: tuple[tuple[str, int], ...] = ()
    required_ops: tuple[tuple[str, tuple[int, ...]], ...] = ()
    search_expansions: int = 0
    budget_exhausted: bool = False
    version: str = FEASIBILITY_VERSION

    @property
    def digest(self) -> str:
        payload = {
            "version": self.version,
            "world_id": self.world_id,
            "region": list(self.region),
            "relationship": [tuple(item) for item in self.relationship],
            "observed_tiles": self.observed_tiles,
            "stops": [self.pickups, self.deliveries],
            "segment_counts": list(self.segment_counts),
            "code": self.code,
            "detail": self.detail,
            "corridor": list(self.corridor),
            "corridor_segment_counts": list(self.corridor_segment_counts),
            "required_ops": [[kind, list(tids)] for kind, tids in self.required_ops],
            "search_expansions": self.search_expansions,
            "budget_exhausted": self.budget_exhausted,
        }
        return sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def as_dict(self) -> dict:
        """Stable JSON projection for diagnostics output."""
        return dict(
            version=self.version,
            world_id=self.world_id,
            map=[self.map_width, self.map_height],
            region=list(self.region),
            relationship=[tuple(item) for item in self.relationship],
            observed_tiles=self.observed_tiles,
            pickups=self.pickups,
            deliveries=self.deliveries,
            segment_counts=self.segment_counts,
            code=self.code,
            detail=self.detail,
            corridor=list(self.corridor),
            corridor_segment_counts=self.corridor_segment_counts,
            required_ops=[[kind, list(tids)] for kind, tids in self.required_ops],
            search_expansions=self.search_expansions,
            budget_exhausted=self.budget_exhausted,
            digest=self.digest,
        )


def _relationship(facts: SupplementalPlanningFacts) -> tuple[tuple[str, int, int], ...]:
    observed = {(scope.role, scope.industry_id, scope.cargo_id) for scope in facts.coverage_scopes}
    return tuple(sorted(observed))


def _feasibility_code_for_tier(tier: int, corridor: tuple[int, ...], segments) -> str:
    histogram = {cls: 0 for cls in SegmentClass}
    for tile_id in corridor:
        histogram[segments[tile_id][0]] += 1
    if tier >= 1 and histogram[SegmentClass.UNKNOWN_OCCUPANCY]:
        return FeasibilityCode.INCOMPLETE_TILE_CLASSIFICATION
    if histogram[SegmentClass.UNSUPPORTED_CONSTRUCTION]:
        return FeasibilityCode.UNSUPPORTED_CONSTRUCTION
    if histogram[SegmentClass.SUPPORTED_CLEARING] or histogram[SegmentClass.TERRAIN_MODIFICATION]:
        return FeasibilityCode.TERRAIN_MODIFICATION_REQUIRED
    assert tier == 0 and not any(
        histogram[cls] for cls in SegmentClass if cls is not SegmentClass.ROAD_BUILDABLE
    )
    return FeasibilityCode.CONNECTED_WITHOUT_MODIFICATION


def _required_ops(corridor: tuple[int, ...], segments) -> tuple[tuple[str, tuple[int, ...]], ...]:
    buckets: dict[str, list[int]] = {
        "clear": [],
        "terrain": [],
        "unsupported": [],
        "unknown": [],
    }
    for tile_id in corridor:
        segment, _ = segments[tile_id]
        if segment is SegmentClass.SUPPORTED_CLEARING:
            buckets["clear"].append(tile_id)
        elif segment is SegmentClass.TERRAIN_MODIFICATION:
            buckets["terrain"].append(tile_id)
        elif segment is SegmentClass.UNSUPPORTED_CONSTRUCTION:
            buckets["unsupported"].append(tile_id)
        elif segment is SegmentClass.UNKNOWN_OCCUPANCY:
            buckets["unknown"].append(tile_id)
    return tuple((kind, tuple(sorted(tids))) for kind, tids in buckets.items() if tids)


def _best_corridor(paths: dict[int, tuple[int, ...]]) -> tuple[int, ...] | None:
    """Deterministic winner: fewest hops, then lexicographically smallest."""
    if not paths:
        return None
    return min(paths.values(), key=lambda corridor: (len(corridor), corridor))


def assess_world_feasibility(
    facts: SupplementalPlanningFacts,
    eligible_pickups: tuple[int, ...],
    eligible_deliveries: tuple[int, ...],
    *,
    tile_classes: dict[int, str] | None = None,
    tile_flags: dict[int, int] | None = None,
    budget: int = MAX_PATH_EXPANSIONS,
) -> FeasibilityDiagnosis:
    """Classify world feasibility for the assessed relationship offline.

    Three bounded shared-super-source searches run in tier order, reusing the
    planner search and budgets: (1) tiles supporting road/terrain construction,
    (2) plus tiles with unknown occupancy, (3) plus blocked footprints. The
    corridor is reported under the least-invasive tier in which it connects;
    codes follow :class:`FeasibilityCode` and the shared budget is reported as
    ``SEARCH_BUDGET_EXCEEDED`` when the tier-1 determination could not finish.
    ``tile_flags`` carries the schema-2 native predicate masks; when given,
    each shared predicate bit must project into the legacy ``TileFact``
    exactly (same capture instant) or the tile reports UNKNOWN. No
    construction is planned, executed or priced; for supported tiles the
    outcome records which tiles need clearing or corner correction, while the
    authoritative grouped operations come from :func:`plan_bounded_levelling`.
    """
    if not eligible_pickups or not eligible_deliveries:
        return FeasibilityDiagnosis(
            world_id=facts.source.world_id,
            map_width=facts.source.map_width,
            map_height=facts.source.map_height,
            region=(
                facts.region.x,
                facts.region.y,
                facts.region.width,
                facts.region.height,
            ),
            relationship=_relationship(facts),
            observed_tiles=len(facts.tiles),
            pickups=len(eligible_pickups),
            deliveries=len(eligible_deliveries),
            segment_counts=(),
            code=FeasibilityCode.NO_CONNECTED_CORRIDOR,
            detail="both eligible stop sets are required",
        )
    facts_tiles = {t.tile_id: t for t in facts.tiles}
    width = facts.source.map_width
    segments = {
        tile_id: classify_segment(
            tile,
            None if tile_classes is None else tile_classes.get(tile_id),
            flags=None if tile_flags is None else tile_flags.get(tile_id),
        )
        for tile_id, tile in facts_tiles.items()
    }
    counts: dict[str, int] = {}
    for segment, _reason in segments.values():
        counts[segment.value] = counts.get(segment.value, 0) + 1
    base = {
        "region": (
            facts.region.x,
            facts.region.y,
            facts.region.width,
            facts.region.height,
        ),
        "relationship": _relationship(facts),
        "observed_tiles": len(facts.tiles),
        "pickups": len(eligible_pickups),
        "deliveries": len(eligible_deliveries),
        "segment_counts": tuple(sorted(counts.items())),
    }

    def with_code(code, detail, corridor, expansions, exhausted):
        corridor = corridor or ()
        histogram: dict[str, int] = {}
        for tile_id in corridor:
            segment = segments[tile_id][0]
            histogram[segment.value] = histogram.get(segment.value, 0) + 1
        return FeasibilityDiagnosis(
            world_id=facts.source.world_id,
            map_width=facts.source.map_width,
            map_height=facts.source.map_height,
            **base,
            code=code,
            detail=detail,
            corridor=corridor,
            corridor_segment_counts=tuple(sorted(histogram.items())),
            required_ops=_required_ops(corridor, segments),
            search_expansions=expansions,
            budget_exhausted=exhausted,
        )

    tier_filters = (
        SUPPORTED_SEGMENT_CLASSES,
        (*SUPPORTED_SEGMENT_CLASSES, SegmentClass.UNKNOWN_OCCUPANCY),
        (
            SegmentClass.ROAD_BUILDABLE,
            *SUPPORTED_SEGMENT_CLASSES[1:],
            SegmentClass.UNKNOWN_OCCUPANCY,
            SegmentClass.UNSUPPORTED_CONSTRUCTION,
        ),
    )
    expansions_used = 0
    best_overall = None
    for tier, allowed in enumerate(tier_filters):
        hostable = {
            tile_id: tile
            for tile_id, tile in facts_tiles.items()
            if segments[tile_id][0] in allowed
        }
        remaining = max(0, budget - expansions_used)
        reached, expansions = _levelling_search(
            eligible_pickups, eligible_deliveries, hostable, facts_tiles, width, remaining
        )
        expansions_used += expansions
        if tier == 0 and remaining == 0 and expansions == 0:
            return with_code(
                FeasibilityCode.SEARCH_BUDGET_EXCEEDED,
                "assessment budget exhausted before the tier completed",
                None,
                expansions_used,
                True,
            )
        corridor = _best_corridor(reached) if reached is not None else None
        if reached is None:
            # Budget exhausted before this tier could settle its frontier.
            return with_code(
                FeasibilityCode.SEARCH_BUDGET_EXCEEDED,
                "assessment budget exhausted before the tier completed",
                best_overall,
                expansions_used,
                True,
            )
        if corridor is not None:
            best_overall = corridor
            code = _feasibility_code_for_tier(tier, corridor, segments)
            # The detail names the failing corridor composition precisely:
            # higher-tier corridors can mix the blocker classes.
            mixed = {
                0: "corridor within supported construction classes",
                1: "corridor exists only through tiles with unknown occupancy",
                2: "corridor exists only through unsupported construction classes"
                if not any(
                    segments[tile_id][0] is SegmentClass.UNKNOWN_OCCUPANCY for tile_id in corridor
                )
                else "corridor blocked by unknown occupancy and unsupported construction tiles",
            }
            return with_code(code, mixed[tier], corridor, expansions_used, False)
        if remaining == 0 and tier < len(tier_filters) - 1:
            # Tier 2/3 still pending but no budget left for them: surface the
            # budget state instead of an unsupported-construction conclusion.
            return with_code(
                FeasibilityCode.SEARCH_BUDGET_EXCEEDED,
                "assessment budget exhausted before lower tiers completed",
                None,
                expansions_used,
                True,
            )
    return with_code(
        FeasibilityCode.NO_CONNECTED_CORRIDOR,
        "no bounded route connects the eligible stops under any classified tier",
        None,
        expansions_used,
        False,
    )
