"""Bounded terraforming expectation compiler for retained P08 proposals (PLANNING_ONLY).

This module transforms a retained bounded ``TerrainProposal`` into an ordered,
deterministic terraform execution specification: for every corner operation it
derives the shared map point, the four directly sharing tiles, exact before and
after corner heights/slope/min-height per tile, the required earlier clearing
operations and the covered observation boundary. A running height model -
started from the retained census and advanced through the sorted operation
sequence - proves for every operation that the native edge invariant
(``|delta| <= 1`` between the terraformed tile height and each edge-neighbour
tile height, verified against official ``TerraformTileHeight`` behavior) still
holds, so no cascading terraform effect can escape the observed boundary.

Every value here is derived offline from the retained Seed 17 census and is
inferior to a fresh native read: the spec is labeled ``PLANNING_ONLY``/``DERIVED``,
never issues a native command, and invents no native cost. Actual spend must be
quoted by the native command layer at execution time. The D2 clearing ceremony
(operator authorization, runtime freeze, dependency identity, immutable
environment, one-shot claims, signed replay) remains the only security
boundary; this module adds no authorization of its own.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

from app.planning.p08_terrain import (
    CAPEX_CATEGORY_TERRAIN,
    CORNER_BITS,
    CORNER_NAMES,
    CORNER_POINT_OFFSET,
    DIRECTIONS,
    MAX_TERRAIN_CLEARED_TILES,
    MAX_TERRAIN_CORNER_OPS,
    MAX_TERRAIN_CORRIDOR_INTERIOR,
    MAX_TERRAIN_HEIGHT_DELTA_STEPS,
    MAX_TERRAIN_REGION_TILES,
    PROPOSAL_VERSION,
    SLOPE_HALFTILE_MIN,
    SLOPE_STEEP,
    TerrainOp,
    TerrainProposal,
    _corridor_class,
    _requires_clearing,
    corner_heights,
)
from app.simulation.openttd.supplemental_planning_facts import SupplementalPlanningFacts
from app.simulation.openttd.terrain_terraform import TerraformExpectation, TerraformShareState

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Mapping

SPEC_VERSION = "p08-terraform-spec/1"

Point = tuple[int, int]

# Orthogonally adjacent corner-point watchers for the native edge invariant.
BOUNDARIES = ((1, 0), (-1, 0), (0, 1), (0, -1))


class TerraformSpecCode:
    """Structured offline compiler outcomes; no native mutation is implied."""

    UNSUPPORTED_PROPOSAL = "UNSUPPORTED_PROPOSAL"
    MISSING_SOURCE_FACTS = "MISSING_SOURCE_FACTS"
    INCONSISTENT_SOURCE_HEIGHTS = "INCONSISTENT_SOURCE_HEIGHTS"
    UNSUPPORTED_GEOMETRY = "UNSUPPORTED_GEOMETRY"
    UNSUPPORTED_SLOPE_ENCODING = "UNSUPPORTED_SLOPE_ENCODING"
    UNSUPPORTED_CLEAR_TARGET = "UNSUPPORTED_CLEAR_TARGET"
    UNKNOWN_TILE_OCCUPANCY = "UNKNOWN_TILE_OCCUPANCY"
    FORBIDDEN_REGION_TILE = "FORBIDDEN_REGION_TILE"
    OUT_OF_REGION_EFFECT = "OUT_OF_REGION_EFFECT"
    DUPLICATE_CORNER_OP = "DUPLICATE_CORNER_OP"
    INVALID_OPERATION_ORDERING = "INVALID_OPERATION_ORDERING"
    MISSING_CLEARING_PREREQUISITE = "MISSING_CLEARING_PREREQUISITE"
    DUPLICATE_CLEAR_OP = "DUPLICATE_CLEAR_OP"
    UNSUPPORTED_CASCADING_EFFECT = "UNSUPPORTED_CASCADING_EFFECT"
    TERRAIN_BUDGET_EXCEEDED = "TERRAIN_BUDGET_EXCEEDED"
    INVALID_OBSERVATION_SCOPE = "INVALID_OBSERVATION_SCOPE"
    UNCOVERED_OBSERVATION_BOUNDARY = "UNCOVERED_OBSERVATION_BOUNDARY"


@dataclass(frozen=True)
class TerraformSpecRejection:
    """Compiler refusal with the exact offline justification."""

    code: str
    detail: str
    op_index: int | None = None


@dataclass(frozen=True)
class TerraformTileShift:
    """Model-derived geometry of one tile before and after one point write."""

    tile_id: int
    corner: str  # the corner of this tile that moves with the shared point; "" for clears
    before_min_height: int
    before_slope: int
    before_corner_heights: dict[str, int]  # keyed by CORNER_NAMES
    after_min_height: int
    after_slope: int
    after_corner_heights: dict[str, int]

    def to_payload(self) -> dict:
        return {
            "tile": self.tile_id,
            "corner": self.corner,
            "before_min": self.before_min_height,
            "before_slope": self.before_slope,
            "before_corners": {name: self.before_corner_heights[name] for name in CORNER_NAMES},
            "after_min": self.after_min_height,
            "after_slope": self.after_slope,
            "after_corners": {name: self.after_corner_heights[name] for name in CORNER_NAMES},
        }


@dataclass(frozen=True)
class TerraformSpecOp:
    """One bounded operation in execution order with derived expectations."""

    op_index: int
    kind: Literal["clear", "raise", "lower"]
    tile_id: int  # proposal host tile; for clears the tile demolish by the D2 ceremony
    before_height: int
    target_height: int
    corner: str | None
    corner_mask: int | None  # official single-bit slope constant for the corner
    direction: Literal["up", "down"] | None
    shared_point: Point | None
    sharing_tiles: tuple[int, ...] | None  # the four tiles sharing the written point
    edge_watch_points: tuple[Point, ...] | None  # orthogonal point watchers (proof)
    shifts: tuple[TerraformTileShift, ...] | None  # one per sharing tile, tile-id order
    required_earlier_clearings: tuple[int, ...]  # op indices that must complete first
    native_command: str | None  # GSTile.RaiseTile / GSTile.LowerTile; clears use D2
    expected_classification: str | None  # clearing ops: the census clearing class

    @property
    def delta(self) -> int | None:
        return None if self.kind == "clear" else self.target_height - self.before_height

    def to_payload(self) -> dict:
        return {
            "index": self.op_index,
            "kind": self.kind,
            "tile": self.tile_id,
            "corner": self.corner,
            "mask": self.corner_mask,
            "direction": self.direction,
            "before": self.before_height,
            "target": self.target_height,
            "point": list(self.shared_point) if self.shared_point else None,
            "sharing": list(self.sharing_tiles) if self.sharing_tiles else None,
            "watch": [list(p) for p in self.edge_watch_points] if self.edge_watch_points else None,
            "clear_ops": list(self.required_earlier_clearings),
            "command": self.native_command,
            "classification": self.expected_classification,
            "shifts": [shift.to_payload() for shift in (self.shifts or ())],
        }


BUDGET_LIMITS: dict[str, int] = {
    "corner_ops": MAX_TERRAIN_CORNER_OPS,
    "cleared_tiles": MAX_TERRAIN_CLEARED_TILES,
    "height_delta_steps": MAX_TERRAIN_HEIGHT_DELTA_STEPS,
    "region_tiles": MAX_TERRAIN_REGION_TILES,
    "corridor_interior": MAX_TERRAIN_CORRIDOR_INTERIOR,
}


@dataclass(frozen=True)
class TerraformSpec:
    """Planning-only deterministic execution specification for one proposal.

    ``execution_status``/``derivation`` pin every value to the retained census:
    the spec is never executable on its own and requires the separately
    reviewed one-shot native ceremony for any world change.

    A clear operation records ``before_height``/``target_height`` exactly as
    the proposal presents them: they denote the tile's census min height and
    the eventual corridor target height of its later corner correction, **not**
    a clearing-time height change (a demolition never rewrites geometry).
    """

    proposal_digest: str
    ops: tuple[TerraformSpecOp, ...]
    corner_op_count: int
    clearing_op_count: int
    corridor: tuple[int, ...]
    interior_road_tiles: int
    target_height: int
    pickup_stop: int
    delivery_stop: int
    region_tiles: tuple[int, ...]
    halo_tiles: tuple[int, ...]
    observation_tiles: tuple[int, ...]
    final_region_tiles: tuple[TerraformTileShift, ...]
    budgets: dict[str, int]
    proposal_version: str = PROPOSAL_VERSION
    version: str = SPEC_VERSION
    execution_status: Literal["PLANNING_ONLY"] = "PLANNING_ONLY"
    native_execution: Literal["UNSUPPORTED_PENDING_SEPARATE_VALIDATION"] = (
        "UNSUPPORTED_PENDING_SEPARATE_VALIDATION"
    )
    derivation: Literal["DERIVED_FROM_RETAINED_CENSUS"] = "DERIVED_FROM_RETAINED_CENSUS"
    cost_category: str = CAPEX_CATEGORY_TERRAIN
    # Native terraform spend is never derived offline; it requires the fresh
    # native quote of the executing ceremony and then belongs to CAPEX_CATEGORY_TERRAIN.
    terraform_cost_gbp: None = None

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(self.to_payload(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def to_payload(self) -> dict:
        return {
            "version": self.version,
            "proposal_version": self.proposal_version,
            "proposal_digest": self.proposal_digest,
            "target_height": self.target_height,
            "interior_road_tiles": self.interior_road_tiles,
            "pickup_stop": self.pickup_stop,
            "delivery_stop": self.delivery_stop,
            "corridor": list(self.corridor),
            "region": list(self.region_tiles),
            "halo": list(self.halo_tiles),
            "observation": list(self.observation_tiles),
            "corner_op_count": self.corner_op_count,
            "clearing_op_count": self.clearing_op_count,
            "budgets": {key: self.budgets[key] for key in sorted(self.budgets)},
            "ops": [op.to_payload() for op in self.ops],
            "final_region_tiles": [shift.to_payload() for shift in self.final_region_tiles],
            "cost_category": self.cost_category,
        }


def _clearing_class(tile) -> str | None:
    """The census clearing class of a tile fact (TREES/FARM/ROCK/ROUGH)."""
    for attr, name in (("tree", "TREES"), ("farm", "FARM"), ("rock", "ROCK"), ("rough", "ROUGH")):
        if getattr(tile, attr):
            return name
    return None


def _occupancy_rejection(tile) -> TerraformSpecRejection | None:
    """Region occupancy must be classified before any corner write touches it."""
    result = _corridor_class(tile)
    if result in ("clean", "clearing"):
        return None
    if (
        not tile.buildable
        and not _requires_clearing(tile)
        and not any(
            (tile.water, tile.coast, tile.road, tile.rail, tile.water_transport, tile.air_transport)
        )
        and tile.industry_id is None
    ):
        return TerraformSpecRejection(
            TerraformSpecCode.UNKNOWN_TILE_OCCUPANCY,
            f"region tile {tile.tile_id} has an unclassifiable captured obstruction",
        )
    return TerraformSpecRejection(
        TerraformSpecCode.FORBIDDEN_REGION_TILE,
        f"region tile {tile.tile_id} carries a forbidden occupancy",
    )


def _tile_state(tile, heights: dict[Point, int]):
    """Derive (min_height, slope, corner heights) of a tile from the model."""
    corners = {
        name: heights.get((tile.x + dx, tile.y + dy))
        for name, (dx, dy) in CORNER_POINT_OFFSET.items()
    }
    if any(value is None for value in corners.values()):
        return TerraformSpecRejection(
            TerraformSpecCode.MISSING_SOURCE_FACTS,
            f"tile {tile.tile_id} has an uncaptured corner point",
        )
    minimum = min(corners.values())  # type: ignore[type-var]
    slope = 0
    for name in CORNER_NAMES:
        if corners[name] > minimum:  # type: ignore[operator]
            slope |= CORNER_BITS[name]
        if corners[name] > minimum + 1:  # type: ignore[operator]
            return TerraformSpecRejection(
                TerraformSpecCode.UNSUPPORTED_CASCADING_EFFECT,
                f"tile {tile.tile_id} would hold an unmodeled convex slope",
            )
    return minimum, slope, {name: corners[name] for name in CORNER_NAMES}


def compile_terraform_spec(
    proposal: TerrainProposal, facts: SupplementalPlanningFacts
) -> TerraformSpec | TerraformSpecRejection:
    """Compile the retained proposal into a bounded execution specification.

    Deterministic and pure: the same proposal and census always produce the
    same specification digest. Any invariant breach fails closed with a
    structured rejection instead of a degraded plan.
    """
    if not isinstance(proposal, TerrainProposal):
        return TerraformSpecRejection(
            TerraformSpecCode.UNSUPPORTED_PROPOSAL, "a TerrainProposal is required"
        )
    if proposal.version != PROPOSAL_VERSION or proposal.execution_status != "PLANNING_ONLY":
        return TerraformSpecRejection(
            TerraformSpecCode.UNSUPPORTED_PROPOSAL,
            "proposal is not a retained planning-only version",
        )
    if not isinstance(facts, SupplementalPlanningFacts):
        return TerraformSpecRejection(
            TerraformSpecCode.MISSING_SOURCE_FACTS, "a census facts document is required"
        )
    if proposal.height_delta_steps != MAX_TERRAIN_HEIGHT_DELTA_STEPS:
        return TerraformSpecRejection(
            TerraformSpecCode.UNSUPPORTED_GEOMETRY,
            "proposal height steps exceed the reviewed one-step budget",
        )

    width = facts.source.map_width
    height = facts.source.map_height
    tiles: dict[int, object] = {}
    for tile in facts.tiles:
        if tile.tile_id != tile.y * width + tile.x:
            return TerraformSpecRejection(
                TerraformSpecCode.MISSING_SOURCE_FACTS,
                f"tile {tile.tile_id} identity is misaligned for (x, y)",
            )
        tiles[tile.tile_id] = tile
    for scope in (*proposal.corridor, *proposal.region_tiles, *proposal.halo_tiles):
        if scope not in tiles:
            return TerraformSpecRejection(
                TerraformSpecCode.MISSING_SOURCE_FACTS,
                f"observed tile {scope} is missing from the census facts",
            )

    region = list(proposal.region_tiles)
    if len(region) > BUDGET_LIMITS["region_tiles"]:
        return TerraformSpecRejection(
            TerraformSpecCode.TERRAIN_BUDGET_EXCEEDED, "region exceeds the reviewed tile budget"
        )
    if proposal.interior_road_tiles > BUDGET_LIMITS["corridor_interior"]:
        return TerraformSpecRejection(
            TerraformSpecCode.TERRAIN_BUDGET_EXCEEDED,
            "interior road tiles exceed the reviewed corridor budget",
        )

    region_set = set(region)
    region_by_id = {tile.tile_id: tile for tile in facts.tiles if tile.tile_id in region_set}
    for tile_id in region:
        tile = region_by_id[tile_id]
        if tile.slope & SLOPE_STEEP or tile.slope & SLOPE_HALFTILE_MIN:
            return TerraformSpecRejection(
                TerraformSpecCode.UNSUPPORTED_SLOPE_ENCODING,
                f"region tile {tile_id} slope encoding is not a supported land shape",
            )
        code = _occupancy_rejection(tile)
        if code is not None:
            return code
    cleared = {op.tile_id for op in proposal.ops if op.kind == "clear"}
    for tile_id in region:
        tile = region_by_id[tile_id]
        if _requires_clearing(tile) and tile_id not in cleared:
            return TerraformSpecRejection(
                TerraformSpecCode.MISSING_CLEARING_PREREQUISITE,
                f"region tile {tile_id} needs a clearing operation the proposal lacks",
            )

    expected_halo: set[int] = set()
    for tile_id in region:
        tile = region_by_id[tile_id]
        for dx, dy in DIRECTIONS:
            neighbor = tiles.get((tile.y + dy) * width + tile.x + dx)
            if (
                neighbor is not None
                and neighbor.tile_id != tile.tile_id
                and neighbor.tile_id not in region_set
            ):
                expected_halo.add(neighbor.tile_id)
    if expected_halo != set(proposal.halo_tiles):
        return TerraformSpecRejection(
            TerraformSpecCode.INVALID_OBSERVATION_SCOPE,
            "proposal halo differs from the observed cardinal boundary of the region",
        )

    ops: tuple[TerrainOp, ...] = proposal.ops
    if not ops:
        return TerraformSpecRejection(TerraformSpecCode.MISSING_SOURCE_FACTS, "proposal has no ops")
    if [op.sort_key for op in ops] != [op.sort_key for op in sorted(ops, key=lambda o: o.sort_key)]:
        return TerraformSpecRejection(
            TerraformSpecCode.INVALID_OPERATION_ORDERING,
            "proposal ops must be in the deterministic (tile, kind, corner) order",
        )
    corner_ops = [op for op in ops if op.kind != "clear"]
    clear_ops = [op for op in ops if op.kind == "clear"]
    cleared_tiles = [op.tile_id for op in clear_ops]
    if len(set(cleared_tiles)) != len(cleared_tiles):
        return TerraformSpecRejection(
            TerraformSpecCode.DUPLICATE_CLEAR_OP,
            f"tiles {sorted({t for t in cleared_tiles if cleared_tiles.count(t) > 1})} "
            "carry more than one clearing operation",
        )
    if len(corner_ops) > BUDGET_LIMITS["corner_ops"]:
        return TerraformSpecRejection(
            TerraformSpecCode.TERRAIN_BUDGET_EXCEEDED,
            "corner operations exceed the reviewed budget",
        )
    if len(clear_ops) > BUDGET_LIMITS["cleared_tiles"]:
        return TerraformSpecRejection(
            TerraformSpecCode.TERRAIN_BUDGET_EXCEEDED,
            "clearing operations exceed the reviewed budget",
        )

    heights: dict[Point, int] = {}
    for tile in facts.tiles:
        try:
            derived = corner_heights(tile)
        except ValueError:
            return TerraformSpecRejection(
                TerraformSpecCode.UNSUPPORTED_SLOPE_ENCODING,
                f"captured tile {tile.tile_id} slope encoding is outside the fact contract",
            )
        for name in CORNER_NAMES:
            point = (tile.x + CORNER_POINT_OFFSET[name][0], tile.y + CORNER_POINT_OFFSET[name][1])
            if point in heights and heights[point] != derived[name]:
                return TerraformSpecRejection(
                    TerraformSpecCode.INCONSISTENT_SOURCE_HEIGHTS,
                    f"two census tiles derive different heights for point {point}",
                )
            heights[point] = derived[name]

    observation = tuple(sorted(region_set | set(proposal.halo_tiles)))
    spec_ops: list[TerraformSpecOp] = []
    written: set[Point] = set()
    context: Mapping[str, object] = {
        "tiles": tiles,
        "region_by_id": region_by_id,
        "region": region_set,
        "heights": heights,
        "written": written,
        "width": width,
        "height": height,
        "observation": set(observation),
    }
    for op_index, op in enumerate(ops):
        spec = _compile_op(op, op_index=op_index, proposal=proposal, context=context)
        if isinstance(spec, TerraformSpecRejection):
            return spec
        spec_ops.append(spec)

    final_region: list[TerraformTileShift] = []
    for tile_id in region:
        tile = region_by_id[tile_id]
        state = _tile_state(tile, heights)
        if isinstance(state, TerraformSpecRejection):
            return state
        minimum, slope, corners = state
        final_region.append(
            TerraformTileShift(
                tile_id=tile_id,
                corner="",
                before_min_height=tile.min_height,
                before_slope=tile.slope,
                before_corner_heights=dict(corner_heights(tile)),
                after_min_height=minimum,
                after_slope=slope,
                after_corner_heights=corners,
            )
        )

    # Execution order: the D2 clearing ceremony is hoisted to the front and
    # the corner writes follow in the proposal's own deterministic (tile,
    # kind, corner) order. Every corner op needs its host and all four
    # sharing tiles classified-clear at admit time, so a clear operation may
    # never run behind a raise that observes or moves the same point.
    ordered = sorted(spec_ops, key=lambda op: (0 if op.kind == "clear" else 1, op.op_index))
    position_of = {op.op_index: position for position, op in enumerate(ordered)}
    final_ops = []
    for position, op in enumerate(ordered):
        remapped = tuple(position_of[index] for index in op.required_earlier_clearings)
        final_ops.append(
            replace(
                op,
                op_index=position,
                required_earlier_clearings=remapped,
            )
        )

    return TerraformSpec(
        proposal_digest=proposal.digest,
        ops=tuple(final_ops),
        corner_op_count=len(corner_ops),
        clearing_op_count=len(clear_ops),
        corridor=tuple(sorted(proposal.corridor)),
        interior_road_tiles=proposal.interior_road_tiles,
        target_height=proposal.target_height,
        pickup_stop=proposal.pickup_stop,
        delivery_stop=proposal.delivery_stop,
        region_tiles=tuple(sorted(region)),
        halo_tiles=tuple(sorted(proposal.halo_tiles)),
        observation_tiles=observation,
        final_region_tiles=tuple(final_region),
        budgets=dict(BUDGET_LIMITS),
    )


def _compile_op(
    op: TerrainOp, *, op_index: int, proposal: TerrainProposal, context: Mapping[str, object]
) -> TerraformSpecOp | TerraformSpecRejection:
    """Derive the specification entry for one proposal operation."""
    tile = context["tiles"].get(op.tile_id)  # type: ignore[union-attr]
    if tile is None:
        return TerraformSpecRejection(
            TerraformSpecCode.MISSING_SOURCE_FACTS,
            f"operation tile {op.tile_id} is missing from the census facts",
            op_index=op_index,
        )
    if op.kind == "clear":
        return _compile_clear_op(op, op_index=op_index, tile=tile, context=context)
    return _compile_corner_op(op, op_index=op_index, tile=tile, proposal=proposal, context=context)


def _compile_clear_op(
    op: TerrainOp, *, op_index: int, tile, context: Mapping[str, object]
) -> TerraformSpecOp | TerraformSpecRejection:
    """Bounding a clearing operation: the D2 classified ceremony owns the command."""
    region: set[int] = context["region"]  # type: ignore[assignment]
    if op.corners != ():
        return TerraformSpecRejection(
            TerraformSpecCode.UNSUPPORTED_GEOMETRY,
            "a clearing operation carries no corner writes",
            op_index=op_index,
        )
    if tile.tile_id not in region:
        return TerraformSpecRejection(
            TerraformSpecCode.OUT_OF_REGION_EFFECT,
            f"clearing tile {tile.tile_id} lies outside the proposal region",
            op_index=op_index,
        )
    classification = _clearing_class(tile)
    if classification is None:
        return TerraformSpecRejection(
            TerraformSpecCode.UNSUPPORTED_CLEAR_TARGET,
            f"clear tile {tile.tile_id} does not carry a classified clearing obstruction",
            op_index=op_index,
        )
    if op.before_height != tile.min_height:
        return TerraformSpecRejection(
            TerraformSpecCode.UNSUPPORTED_GEOMETRY,
            f"clear before_height {op.before_height} differs from observed {tile.min_height}",
            op_index=op_index,
        )
    return TerraformSpecOp(
        op_index=op_index,
        kind="clear",
        tile_id=tile.tile_id,
        before_height=op.before_height,
        # The proposal's clear-op fields record the census height and the
        # eventual corridor target of this tile's later corner correction;
        # no demolition command changes geometry, so no height delta is
        # claimed here (see the TerraformSpec docstring wrinkle note).
        target_height=op.target_height,
        corner=None,
        corner_mask=None,
        direction=None,
        shared_point=None,
        sharing_tiles=None,
        edge_watch_points=None,
        shifts=None,
        required_earlier_clearings=(),
        # The D2 separately reviewed bounded clearing contract executes this
        # operation; there is no terraform command for it.
        native_command=None,
        expected_classification=classification,
    )


def _compile_corner_op(
    op: TerrainOp, *, op_index: int, tile, proposal: TerrainProposal, context: Mapping[str, object]
) -> TerraformSpecOp | TerraformSpecRejection:
    """Deriving one bounded corner write against the running height model."""
    tiles = context["tiles"]  # type: ignore[var-annotated]
    region_by_id = context["region_by_id"]  # type: ignore[var-annotated]
    region: set[int] = context["region"]  # type: ignore[assignment]
    heights: dict[Point, int] = context["heights"]
    written: set[Point] = context["written"]
    width: int = context["width"]  # type: ignore[assignment]
    observation: set[int] = context["observation"]  # type: ignore[assignment]

    if len(op.corners) != 1:
        return TerraformSpecRejection(
            TerraformSpecCode.UNSUPPORTED_GEOMETRY,
            "each bounded operation writes exactly one corner",
            op_index=op_index,
        )
    if op.tile_id not in region:
        return TerraformSpecRejection(
            TerraformSpecCode.OUT_OF_REGION_EFFECT,
            f"host tile {op.tile_id} lies outside the proposal region",
            op_index=op_index,
        )
    corner = op.corners[0]
    if corner not in CORNER_NAMES:
        return TerraformSpecRejection(
            TerraformSpecCode.UNSUPPORTED_GEOMETRY,
            f"named corner {corner} is outside the four official corners",
            op_index=op_index,
        )
    expected_delta = 1 if op.kind == "raise" else -1
    if op.target_height - op.before_height != expected_delta:
        return TerraformSpecRejection(
            TerraformSpecCode.UNSUPPORTED_GEOMETRY,
            "each bounded corner operation changes height by exactly one step",
            op_index=op_index,
        )
    direction: Literal["up", "down"] = "up" if op.kind == "raise" else "down"
    offset = CORNER_POINT_OFFSET[corner]
    point = (tile.x + offset[0], tile.y + offset[1])
    if point in written:
        return TerraformSpecRejection(
            TerraformSpecCode.DUPLICATE_CORNER_OP,
            f"shared point {point} is written by more than one operation",
            op_index=op_index,
        )
    model_height = heights.get(point)
    if model_height != op.before_height:
        return TerraformSpecRejection(
            TerraformSpecCode.UNSUPPORTED_GEOMETRY,
            f"operation before_height {op.before_height} disagrees with derived "
            f"height {model_height}",
            op_index=op_index,
        )

    px, py = point
    sharing_tiles: list[int] = []
    for x, y in ((px, py), (px - 1, py), (px, py - 1), (px - 1, py - 1)):
        candidate = tiles.get(y * width + x)
        if candidate is None:
            return TerraformSpecRejection(
                TerraformSpecCode.MISSING_SOURCE_FACTS,
                f"sharing tile at {(x, y)} is missing from the census facts",
                op_index=op_index,
            )
        if candidate.tile_id not in region:
            return TerraformSpecRejection(
                TerraformSpecCode.OUT_OF_REGION_EFFECT,
                f"tile {candidate.tile_id} shares the written point but is outside the region",
                op_index=op_index,
            )
        sharing_tiles.append(candidate.tile_id)
    sharing_ids = tuple(sorted(sharing_tiles))

    # Every tile that must already be classified clear at the raise's own admit
    # time - the host and all four directly sharing tiles - drives this
    # operation's clearing prerequisites: the D2 clearing ceremony clears an
    # obstruction BEFORE the corner write may observe or move the shared point.
    needs_clear = [
        tile_id
        for tile_id in sorted({op.tile_id, *sharing_ids})
        if _requires_clearing(context["tiles"][tile_id])
    ]
    clear_position_of: dict[int, int] = {}
    for index, other in enumerate(proposal.ops):
        if other.kind == "clear" and other.tile_id in needs_clear:
            clear_position_of.setdefault(other.tile_id, index)
    unserved = [tile_id for tile_id in needs_clear if tile_id not in clear_position_of]
    if unserved:
        return TerraformSpecRejection(
            TerraformSpecCode.MISSING_CLEARING_PREREQUISITE,
            f"tiles {unserved} require the clearing ceremony but no clear operation is scheduled",
            op_index=op_index,
        )
    # Proposal indices; remapped to the hoisted execution order once the full
    # operation list has been compiled.
    required_clearings = tuple(clear_position_of[tile_id] for tile_id in needs_clear)

    # Edge-invariant watch points: the four orthogonally adjacent corner points
    # whose observed heights must stay within one step of the written height,
    # otherwise the native command would cascade beyond the shared point.
    watch: list[Point] = []
    for ex, ey in BOUNDARIES:
        watcher = (px + ex, py + ey)
        neighbor = heights.get(watcher)
        if neighbor is None:
            return TerraformSpecRejection(
                TerraformSpecCode.UNSUPPORTED_CASCADING_EFFECT,
                f"watched point {watcher} is outside the captured census; "
                "cascading cannot be bounded",
                op_index=op_index,
            )
        if abs(op.target_height - neighbor) > 1:
            return TerraformSpecRejection(
                TerraformSpecCode.UNSUPPORTED_CASCADING_EFFECT,
                f"writing point {point} would cascade into point {watcher}",
                op_index=op_index,
            )
        watch.append(watcher)
    for watcher_point in watch:
        wx, wy = watcher_point
        for x, y in ((wx, wy), (wx - 1, wy), (wx, wy - 1), (wx - 1, wy - 1)):
            seen = tiles.get(y * width + x)
            if seen is None or seen.tile_id not in observation:
                return TerraformSpecRejection(
                    TerraformSpecCode.UNCOVERED_OBSERVATION_BOUNDARY,
                    f"watch boundary tile at {(x, y)} is outside region/halo observation",
                    op_index=op_index,
                )

    shifts = _derive_shifts(
        point=point,
        direction=direction,
        sharing_ids=sharing_ids,
        region_by_id=region_by_id,
        heights=heights,
        width=width,
        tiles=tiles,
        op_index=op_index,
    )
    if isinstance(shifts, TerraformSpecRejection):
        return shifts
    heights[point] = op.target_height
    written.add(point)
    return TerraformSpecOp(
        op_index=op_index,
        kind=op.kind,
        tile_id=op.tile_id,
        before_height=op.before_height,
        target_height=op.target_height,
        corner=corner,
        corner_mask=CORNER_BITS[corner],
        direction=direction,
        shared_point=point,
        sharing_tiles=sharing_ids,
        edge_watch_points=tuple(watch),
        shifts=shifts,
        required_earlier_clearings=required_clearings,
        native_command=f"GSTile.{'RaiseTile' if direction == 'up' else 'LowerTile'}",
        expected_classification=None,
    )


def _derive_shifts(
    *,
    point: Point,
    direction: Literal["up", "down"],
    sharing_ids: tuple[int, ...],
    region_by_id,
    heights,
    width,
    tiles,
    op_index: int,
) -> tuple[TerraformTileShift, ...] | TerraformSpecRejection:
    """Per-tile before/after geometry around the written point."""
    shifts: list[TerraformTileShift] = []
    for tile_id in sharing_ids:
        tile = region_by_id[tile_id]
        state = _tile_state(tile, heights)
        if isinstance(state, TerraformSpecRejection):
            return TerraformSpecRejection(state.code, f"{state.detail} (before)", op_index=op_index)
        before_min, before_slope, before_corners = state
        shifted_corner: str | None = None
        for name in CORNER_NAMES:
            candidate = (
                tile.x + CORNER_POINT_OFFSET[name][0],
                tile.y + CORNER_POINT_OFFSET[name][1],
            )
            if candidate == point:
                shifted_corner = name
                break
        if shifted_corner is None:
            return TerraformSpecRejection(
                TerraformSpecCode.UNSUPPORTED_GEOMETRY,
                f"tile {tile_id} does not share the written point",
                op_index=op_index,
            )
        corner_position = (tile.x, tile.y)
        if tiles.get(corner_position[1] * width + corner_position[0]).tile_id != tile_id:  # type: ignore[union-attr]
            return TerraformSpecRejection(
                TerraformSpecCode.MISSING_SOURCE_FACTS,
                f"tile {tile_id} position identity drifted from the census",
                op_index=op_index,
            )
        after_corners = dict(before_corners)
        after_corners[shifted_corner] += 1 if direction == "up" else -1
        after_min = min(after_corners.values())
        after_slope = 0
        for name in CORNER_NAMES:
            if after_corners[name] > after_min:
                after_slope |= CORNER_BITS[name]
            if after_corners[name] > after_min + 1:
                return TerraformSpecRejection(
                    TerraformSpecCode.UNSUPPORTED_CASCADING_EFFECT,
                    f"tile {tile_id} would need a cascade beyond the command",
                    op_index=op_index,
                )
        shifts.append(
            TerraformTileShift(
                tile_id=tile_id,
                corner=shifted_corner,
                before_min_height=before_min,
                before_slope=before_slope,
                before_corner_heights=before_corners,
                after_min_height=after_min,
                after_slope=after_slope,
                after_corner_heights=after_corners,
            )
        )
    return tuple(shifts)


def intent_expectation(
    spec: TerraformSpec, op_index: int, facts: SupplementalPlanningFacts
) -> TerraformExpectation | TerraformSpecRejection:
    """Bridge a compiled corner operation into the wire-contract expectation.

    A ladder of structural checks runs here, against the census facts document,
    so every derived field - host tile, commanded corner, official single-bit
    mask, shared point and per-tile expected slope blocks - is rebuilt from the
    compiled model and cross-checked before any intent can be admitted. Clear
    operations are out of scope: they belong to the D2 bounded clearing contract.
    """
    if not 0 <= op_index < len(spec.ops):
        return TerraformSpecRejection(
            TerraformSpecCode.UNSUPPORTED_GEOMETRY,
            f"operation index {op_index} is outside the compiled specification",
        )
    op = spec.ops[op_index]
    if isinstance(op, TerraformSpecRejection):  # pragma: no cover - defensive
        return op
    if op.kind == "clear":
        return TerraformSpecRejection(
            TerraformSpecCode.UNSUPPORTED_CLEAR_TARGET,
            "a clearing operation executes under the D2 cleaning contract, not here",
            op_index=op_index,
        )
    width = facts.source.map_width
    height = facts.source.map_height
    tiles = {tile.tile_id: tile for tile in facts.tiles}
    point = op.shared_point
    if point is None or op.sharing_tiles is None or op.shifts is None:
        return TerraformSpecRejection(  # pragma: no cover - compiler invariant
            TerraformSpecCode.UNSUPPORTED_GEOMETRY,
            "corner operation lacks compiled geometry",
            op_index=op_index,
        )
    # Symmetric interior bounds: a shared point may sit on the last column or
    # row of the census rectangle exactly as the y axis already allows.
    if point[0] < 1 or point[1] < 1 or not (1 <= point[0] < width and 1 <= point[1] < height):
        return TerraformSpecRejection(
            TerraformSpecCode.OUT_OF_REGION_EFFECT,
            f"shared point {point} touches the census rectangle border",
            op_index=op_index,
        )
    states: list[TerraformShareState] = []
    for tile_id, shift in zip(op.sharing_tiles, op.shifts, strict=True):
        tile = tiles.get(tile_id)
        if tile is None or tile.tile_id != shift.tile_id:
            return TerraformSpecRejection(
                TerraformSpecCode.MISSING_SOURCE_FACTS,
                f"sharing tile {tile_id} lacks census facts for the intent",
                op_index=op_index,
            )
        expected_corner = next(
            (
                name
                for name in CORNER_NAMES
                if (tile.x + CORNER_POINT_OFFSET[name][0], tile.y + CORNER_POINT_OFFSET[name][1])
                == point
            ),
            None,
        )
        if expected_corner is None:
            return TerraformSpecRejection(
                TerraformSpecCode.UNSUPPORTED_GEOMETRY,
                f"sharing tile {tile_id} does not own a corner of the written point",
                op_index=op_index,
            )
        if expected_corner != shift.corner:
            return TerraformSpecRejection(
                TerraformSpecCode.UNSUPPORTED_GEOMETRY,
                f"tile {tile_id} compiled corner {shift.corner} disagrees with the lattice",
                op_index=op_index,
            )
        states.append(
            TerraformShareState(
                tile=tile_id,
                corner=expected_corner,
                before_min_height=shift.before_min_height,
                before_slope=shift.before_slope,
                after_min_height=shift.after_min_height,
                after_slope=shift.after_slope,
            )
        )
    try:
        return TerraformExpectation(
            host_tile=op.tile_id,
            corner=op.corner,
            direction=op.direction,
            corner_mask=op.corner_mask,
            shared_point_x=point[0],
            shared_point_y=point[1],
            sharing_tiles=op.sharing_tiles,
            tiles=tuple(states),
        )
    except ValueError as error:
        return TerraformSpecRejection(
            TerraformSpecCode.UNSUPPORTED_GEOMETRY,
            str(error),
            op_index=op_index,
        )
