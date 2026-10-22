"""Offline bounded-terraforming specification compiler tests (D3).

Those tests bind the D3 terraforming compiler (``app.planning.p08_terraform``)
to a synthetic point-consistent census recipe and to the sealed Seed 17
retained census: rejection codes, deterministic digests, operation ordering,
budget clamps, clear prerequisites, shared-point maps, observation boundaries
and the prelaunch ``intent_expectation`` bridge. Every structured value is
labelled planning-only; no native execution is claimed anywhere.

Offline only: no OpenTTD launch, no AdminPort connection, no evidence
mutation. Retained-evidence tests skip when the ignored artifacts are absent
from this checkout.
"""

import sys
from dataclasses import replace as dreplace
from functools import lru_cache
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from test_p08_bounded_terrain import facts_at, stops_for
from test_p08_controlled_road import mapped, world_for

from app.planning.p08_terraform import (
    BUDGET_LIMITS,
    SPEC_VERSION,
    TerraformSpecCode,
    compile_terraform_spec,
    intent_expectation,
)
from app.planning.p08_terrain import (
    CORNER_BITS,
    CORNER_POINT_OFFSET,
    MAX_TERRAIN_CLEARED_TILES,
    MAX_TERRAIN_CORNER_OPS,
    MAX_TERRAIN_CORRIDOR_INTERIOR,
    MAX_TERRAIN_HEIGHT_DELTA_STEPS,
    MAX_TERRAIN_REGION_TILES,
    PROPOSAL_VERSION,
    TerrainInfeasibility,
    TerrainOp,
    plan_bounded_levelling,
)
from app.simulation.openttd.supplemental_planning_facts import SupplementalPlanningFacts

REPO = Path(__file__).resolve().parents[1]
RETAINED = (
    REPO / "artifacts/demos/playable-demo-698799a2dfb146948fd2983ff2032253/network-facts-0.json"
)
CANDIDATE = REPO / "artifacts/demos/classification-exec-seed17-3a8f9e46"

SLOPE_STEEP_W = 0x1B  # steep + N|W|S under the official slope_type.h bits

# Synthetic census keys (64x64 fixture world, capture (8, 8)..(18, 16)).
WALL = 650  # wall tile (10, 10): official N|W rise
WALL_NORTH_SHARE = 585  # tile (9, 9), shares the wall's N corner with WALL
WALL_NORTH_HOST = 649  # tile (9, 10)
QUARRY = 841  # region tile (9, 13) inside the levelling region below the wall


def eastwest_recipe(
    world,
    *,
    wall_row=10,
    col=10,
    x0=8,
    y0=8,
    width=11,
    height=9,
    retiles=(),
):
    """Point-consistent pinned-style census: P(x, y) = 1 iff y >= wall_row + 1.

    Tile (x, wall_row) then holds the official N|W rise (slope 0x09 with E and
    S at the base height), exactly like the retained Seed 17 cliff band. Tile
    facts derive from one shared point map, so the census round-trips through
    ``corner_heights`` without inconsistency, and the column stops straddle
    the cliff: the pickup rests south of it, the delivery north.
    """
    raw = facts_at(world, x0, y0, width, height)
    prototype = raw["tiles"][0]
    map_width = world.context.world.map_width
    points = {
        (x, y): (1 if y >= wall_row + 1 else 2)
        for y in range(y0 - 2, y0 + height + 2)
        for x in range(x0 - 2, x0 + width + 2)
    }
    tiles = []
    for y in range(y0, y0 + height):
        for x in range(x0, x0 + width):
            corners = {
                name: points[(x + dx, y + dy)] for name, (dx, dy) in CORNER_POINT_OFFSET.items()
            }
            minimum = min(corners.values())
            slope = 0
            for name, bit in CORNER_BITS.items():
                if corners[name] > minimum:
                    slope |= bit
            tiles.append(
                dict(
                    prototype,
                    tile_id=y * map_width + x,
                    x=x,
                    y=y,
                    min_height=minimum,
                    slope=slope,
                )
            )
    raw["tiles"] = tiles
    pickup_xy = (col, y0 + height - 3)
    delivery_xy = (col, y0)
    raw["coverage"] = [
        dict(
            tile_id=y * map_width + x,
            **scope,
            producer_count=1,
            acceptance_eighths=8,
            industry_covered=(
                (x, y) == pickup_xy if scope["role"] == "pickup" else (x, y) == delivery_xy
            ),
        )
        for y in range(y0, y0 + height)
        for x in range(x0, x0 + width)
        for scope in raw["coverage_scopes"]
    ]
    for (x, y), fields in retiles:
        tile = next(t for t in raw["tiles"] if (t["x"], t["y"]) == (x, y))
        tile.update(fields)
    return raw


def expected_halo(region_ids, tiles_by_id, width):
    """Cardinal boundary of the region, computed with the compiler's formula."""
    region = set(region_ids)
    out = set()
    for tile_id in region:
        tile = tiles_by_id[tile_id]
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            neighbor = tiles_by_id.get((tile.y + dy) * width + tile.x + dx)
            if neighbor is None or (neighbor.x, neighbor.y) != (tile.x + dx, tile.y + dy):
                continue
            if neighbor.tile_id not in region:
                out.add(neighbor.tile_id)
    return tuple(sorted(out))


def tiles_of(value):
    return {tile.tile_id: tile for tile in value.facts.tiles}


def sort_ops(ops):
    return tuple(sorted(ops, key=lambda op: op.sort_key))


@pytest.fixture(scope="module")
def world():
    return world_for(accepts=(1,))


@pytest.fixture(scope="module")
def levelled(world):
    """A fully supported levelling the D3 compiler accepts (ten S raises)."""
    value = mapped(world, eastwest_recipe(world))
    pickups, deliveries = stops_for(value)
    proposal = plan_bounded_levelling(value.facts, pickups, deliveries)
    assert not isinstance(proposal, TerrainInfeasibility)
    spec = compile_terraform_spec(proposal, value.facts)
    assert not hasattr(spec, "code"), (spec.code, spec.detail)
    return value, proposal, spec


@pytest.fixture(scope="module")
def tree_plan(world, levelled):
    """A plan with one classified TREES clearing injected on QUARRY.

    The clearing obstruction comes from tree-flagged census facts (same point
    map); the clean proposal is reused, so compiled geometry stays identical.
    """
    _value, proposal, _spec = levelled
    treeted = mapped(world, eastwest_recipe(world, retiles=(((9, 13), {"tree": True}),)))
    crafted = dreplace(
        proposal,
        ops=sort_ops((TerrainOp("clear", QUARRY, (), 1, 2), *proposal.ops)),
    )
    spec = compile_terraform_spec(crafted, treeted.facts)
    assert not hasattr(spec, "code"), (spec.code, spec.detail)
    return treeted, crafted, spec


def _crafted(levelled, *ops, region_ids=()):
    """Compile an operation-crafted plan under the compiler's own halo rule."""
    value, proposal, _spec = levelled
    region = tuple(sorted(set(proposal.region_tiles) | set(region_ids)))
    halo = expected_halo(region, tiles_of(value), value.facts.source.map_width)
    plan = dreplace(proposal, ops=sort_ops(ops), region_tiles=region, halo_tiles=halo)
    return compile_terraform_spec(plan, value.facts)


# ---------------------------------------------------------------------------
# Structured rejection of malformed inputs
# ---------------------------------------------------------------------------


def test_rejects_non_proposal_inputs(levelled):
    value, proposal, _spec = levelled
    rejection = compile_terraform_spec(object(), value.facts)
    assert rejection.code == TerraformSpecCode.UNSUPPORTED_PROPOSAL
    rejection = compile_terraform_spec(
        dreplace(proposal, version="terrain-proposal-v9"), value.facts
    )
    assert rejection.code == TerraformSpecCode.UNSUPPORTED_PROPOSAL
    rejection = compile_terraform_spec(
        dreplace(proposal, execution_status="EXECUTABLE"), value.facts
    )
    assert rejection.code == TerraformSpecCode.UNSUPPORTED_PROPOSAL
    rejection = compile_terraform_spec(dreplace(proposal, height_delta_steps=2), value.facts)
    assert rejection.code == TerraformSpecCode.UNSUPPORTED_GEOMETRY


def test_rejects_missing_or_unsupported_facts(levelled):
    value, proposal, _spec = levelled
    rejection = compile_terraform_spec(proposal, object())
    assert rejection.code == TerraformSpecCode.MISSING_SOURCE_FACTS
    assert "census facts document is required" in rejection.detail
    rejection = compile_terraform_spec(dreplace(proposal, ops=()), value.facts)
    assert rejection.code == TerraformSpecCode.MISSING_SOURCE_FACTS
    assert "no ops" in rejection.detail


def test_rejects_uncaptured_observation_scope(levelled):
    value, proposal, _spec = levelled
    rejection = compile_terraform_spec(dreplace(proposal, halo_tiles=()), value.facts)
    assert rejection.code == TerraformSpecCode.INVALID_OBSERVATION_SCOPE
    assert "halo differs" in rejection.detail


def test_budgets_mirror_the_reviewed_module_constants():
    assert BUDGET_LIMITS == {
        "corner_ops": MAX_TERRAIN_CORNER_OPS,
        "cleared_tiles": MAX_TERRAIN_CLEARED_TILES,
        "region_tiles": MAX_TERRAIN_REGION_TILES,
        "corridor_interior": MAX_TERRAIN_CORRIDOR_INTERIOR,
        "height_delta_steps": MAX_TERRAIN_HEIGHT_DELTA_STEPS,
    }


def test_rejects_region_budget(levelled):
    value, proposal, _spec = levelled
    rejection = compile_terraform_spec(
        dreplace(proposal, region_tiles=proposal.region_tiles * 150), value.facts
    )
    assert rejection.code == TerraformSpecCode.TERRAIN_BUDGET_EXCEEDED
    assert "region exceeds" in rejection.detail


def test_rejects_interior_corridor_budget(levelled):
    value, proposal, _spec = levelled
    rejection = compile_terraform_spec(
        dreplace(proposal, interior_road_tiles=MAX_TERRAIN_CORRIDOR_INTERIOR + 1),
        value.facts,
    )
    assert rejection.code == TerraformSpecCode.TERRAIN_BUDGET_EXCEEDED
    assert "interior road tiles" in rejection.detail


def test_rejects_corner_op_budget(levelled, monkeypatch):
    value, proposal, _spec = levelled
    monkeypatch.setattr(
        "app.planning.p08_terraform.BUDGET_LIMITS", dict(BUDGET_LIMITS, corner_ops=0)
    )
    rejection = compile_terraform_spec(proposal, value.facts)
    assert rejection.code == TerraformSpecCode.TERRAIN_BUDGET_EXCEEDED
    assert "corner operations exceed" in rejection.detail


# ---------------------------------------------------------------------------
# Census-consistency and occupancy rejections
# ---------------------------------------------------------------------------


def test_rejects_inconsistent_shared_point_heights(world, levelled):
    value, proposal, _spec = levelled
    lifted = mapped(world, eastwest_recipe(world, retiles=(((10, 9), {"slope": 0x1}),)))
    rejection = compile_terraform_spec(proposal, lifted.facts)
    assert rejection.code == TerraformSpecCode.INCONSISTENT_SOURCE_HEIGHTS
    assert "point (11, 9)" in rejection.detail


def test_rejects_unknown_region_occupancy(world, levelled):
    value, proposal, _spec = levelled
    mixed = mapped(world, eastwest_recipe(world, retiles=(((10, 10), {"buildable": False}),)))
    rejection = compile_terraform_spec(proposal, mixed.facts)
    assert rejection.code == TerraformSpecCode.UNKNOWN_TILE_OCCUPANCY
    assert "unclassifiable captured obstruction" in rejection.detail


def test_rejects_forbidden_region_occupancy(world, levelled):
    value, proposal, _spec = levelled
    roaded = mapped(world, eastwest_recipe(world, retiles=(((10, 10), {"road": True}),)))
    rejection = compile_terraform_spec(proposal, roaded.facts)
    assert rejection.code == TerraformSpecCode.FORBIDDEN_REGION_TILE


def test_rejects_unsupported_slope_encoding(world, levelled):
    value, proposal, _spec = levelled
    steep = mapped(world, eastwest_recipe(world, retiles=(((10, 10), {"slope": SLOPE_STEEP_W}),)))
    rejection = compile_terraform_spec(proposal, steep.facts)
    assert rejection.code == TerraformSpecCode.UNSUPPORTED_SLOPE_ENCODING
    assert "supported land shape" in rejection.detail


def test_rejects_missing_clearing_prerequisite(tree_plan):
    """Dropping the injected clear leaves the region tree without its prerequisite."""
    value, proposal, _spec = tree_plan
    kept = tuple(op for op in proposal.ops if op.kind != "clear")
    rejection = compile_terraform_spec(dreplace(proposal, ops=kept), value.facts)
    assert rejection.code == TerraformSpecCode.MISSING_CLEARING_PREREQUISITE
    assert "clearing operation the proposal lacks" in rejection.detail


# ---------------------------------------------------------------------------
# Operation-shape rejections (crafted plan replacements on the clean census)
# ---------------------------------------------------------------------------


def test_rejects_multi_corner_operation(levelled):
    _value, _proposal, _spec = levelled
    crafted = TerrainOp("raise", WALL, ("E", "S"), 1, 2)
    rejection = _crafted(levelled, crafted)
    assert rejection.code == TerraformSpecCode.UNSUPPORTED_GEOMETRY
    assert "writes exactly one corner" in rejection.detail


def test_rejects_operation_outside_region(levelled):
    _value, _proposal, _spec = levelled
    rejection = _crafted(levelled, TerrainOp("raise", 8 * 64 + 8, ("E",), 1, 2))
    assert rejection.code == TerraformSpecCode.OUT_OF_REGION_EFFECT
    assert "outside the proposal region" in rejection.detail


def test_rejects_uncaptured_operation_tile(levelled):
    _value, _proposal, _spec = levelled
    rejection = _crafted(levelled, TerrainOp("raise", 20 * 64 + 20, ("E",), 1, 2))
    assert rejection.code == TerraformSpecCode.MISSING_SOURCE_FACTS
    assert "missing from the census facts" in rejection.detail


def test_rejects_unknown_corner_name(levelled):
    _value, _proposal, _spec = levelled
    rejection = _crafted(levelled, TerrainOp("raise", WALL, ("X",), 1, 2))
    assert rejection.code == TerraformSpecCode.UNSUPPORTED_GEOMETRY
    assert "official corners" in rejection.detail


def test_rejects_non_single_step_delta(levelled):
    _value, _proposal, _spec = levelled
    rejection = _crafted(levelled, TerrainOp("raise", WALL, ("E",), 1, 3))
    assert rejection.code == TerraformSpecCode.UNSUPPORTED_GEOMETRY
    assert "exactly one step" in rejection.detail


def test_rejects_stale_before_height(levelled):
    _value, _proposal, _spec = levelled
    rejection = _crafted(levelled, TerrainOp("raise", WALL, ("E",), 5, 6))
    assert rejection.code == TerraformSpecCode.UNSUPPORTED_GEOMETRY
    assert "before_height 5 disagrees" in rejection.detail


def test_rejects_duplicate_corner_write(levelled):
    _value, _proposal, _spec = levelled
    first = TerrainOp("raise", 649, ("S",), 1, 2)
    second = TerrainOp("raise", 650, ("E",), 1, 2)
    rejection = _crafted(levelled, first, second)
    assert rejection.code == TerraformSpecCode.DUPLICATE_CORNER_OP
    assert "written by more than one operation" in rejection.detail


def test_rejects_unordered_operations(levelled):
    value, proposal, _spec = levelled
    rejection = compile_terraform_spec(
        dreplace(proposal, ops=tuple(reversed(proposal.ops))), value.facts
    )
    assert rejection.code == TerraformSpecCode.INVALID_OPERATION_ORDERING
    assert "(tile, kind, corner)" in rejection.detail


def test_rejects_write_outside_the_census_cascade(levelled):
    """A write whose watch point runs off the captured census cannot be bounded."""
    _value, _proposal, _spec = levelled
    width = 64
    injections = {y * width + x for x, y in ((8, 15), (8, 16), (9, 16))}
    op = TerrainOp("raise", 15 * 64 + 9, ("E",), 1, 2)
    rejection = _crafted(levelled, op, region_ids=injections)
    assert rejection.code == TerraformSpecCode.UNCOVERED_OBSERVATION_BOUNDARY
    assert "watch boundary tile" in rejection.detail


def test_rejects_cascading_raise(levelled):
    """Raising an already-raised corner would step past its watched neighbor."""
    _value, _proposal, _spec = levelled
    injections = {WALL_NORTH_SHARE, WALL_NORTH_HOST}
    op = TerrainOp("raise", WALL, ("N",), 2, 3)
    rejection = _crafted(levelled, op, region_ids=injections)
    assert rejection.code == TerraformSpecCode.UNSUPPORTED_CASCADING_EFFECT
    assert "would cascade into point" in rejection.detail


# ---------------------------------------------------------------------------
# Clearing-operation bounding and budget
# ---------------------------------------------------------------------------


def test_tree_clear_operation_compiles_with_classification(tree_plan):
    _value, _proposal, spec = tree_plan
    clearers = [op for op in spec.ops if op.kind == "clear"]
    assert len(clearers) == 1
    clear = clearers[0]
    assert clear.tile_id == QUARRY
    assert (clear.corner, clear.corner_mask, clear.direction) == (None, None, None)
    assert clear.shared_point is None
    assert clear.sharing_tiles is None and clear.shifts is None
    assert clear.edge_watch_points is None
    assert clear.native_command is None
    assert clear.expected_classification == "TREES"
    assert clear.required_earlier_clearings == ()


def test_clear_host_raise_carries_the_earlier_clearing(tree_plan):
    _value, _proposal, spec = tree_plan
    index = next(i for i, op in enumerate(spec.ops) if op.kind == "clear")
    host = next(op for op in spec.ops if op.kind != "clear" and op.tile_id == QUARRY)
    assert host.required_earlier_clearings == (index,)


def test_clearing_ops_budget(tree_plan, monkeypatch):
    value, proposal, _spec = tree_plan
    monkeypatch.setattr(
        "app.planning.p08_terraform.BUDGET_LIMITS", dict(BUDGET_LIMITS, cleared_tiles=0)
    )
    rejection = compile_terraform_spec(proposal, value.facts)
    assert rejection.code == TerraformSpecCode.TERRAIN_BUDGET_EXCEEDED
    assert "clearing operations exceed" in rejection.detail


def test_clear_of_unobstructed_tile_is_unsupported(levelled):
    _value, _proposal, _spec = levelled
    clear = TerrainOp("clear", WALL, (), 1, 2)
    rejection = _crafted(levelled, clear)
    assert rejection.code == TerraformSpecCode.UNSUPPORTED_CLEAR_TARGET
    assert "classified clearing obstruction" in rejection.detail


def test_clear_with_corner_write_is_rejected(tree_plan):
    value, proposal, _spec = tree_plan
    crafted = TerrainOp("clear", QUARRY, ("E",), 1, 2)
    ops = [crafted if op.kind == "clear" else op for op in proposal.ops]
    rejection = compile_terraform_spec(dreplace(proposal, ops=sort_ops(ops)), value.facts)
    assert rejection.code == TerraformSpecCode.UNSUPPORTED_GEOMETRY
    assert "carries no corner writes" in rejection.detail


def test_clear_before_height_disagreement(tree_plan):
    value, proposal, _spec = tree_plan
    crafted = TerrainOp("clear", QUARRY, (), 3, 2)
    ops = [crafted if op.kind == "clear" else op for op in proposal.ops]
    rejection = compile_terraform_spec(dreplace(proposal, ops=sort_ops(ops)), value.facts)
    assert rejection.code == TerraformSpecCode.UNSUPPORTED_GEOMETRY
    assert "clear before_height 3 differs" in rejection.detail


def test_official_corner_lattice_bits():
    """Corner names, masks and shared-point offsets match the official model."""
    assert CORNER_BITS == {"N": 0x8, "E": 0x4, "W": 0x1, "S": 0x2}
    assert CORNER_POINT_OFFSET == {"N": (0, 0), "E": (0, 1), "W": (1, 0), "S": (1, 1)}


# ---------------------------------------------------------------------------
# The accepted specification: shape, ordering, determinism, intent bridge
# ---------------------------------------------------------------------------


def test_compiled_spec_is_deterministic_with_stable_digest(levelled):
    value, proposal, spec = levelled
    again = compile_terraform_spec(proposal, value.facts)
    assert spec.digest == again.digest
    assert spec.version == SPEC_VERSION == "p08-terraform-spec/1"
    assert spec.proposal_version == PROPOSAL_VERSION
    assert spec.execution_status == "PLANNING_ONLY"
    assert spec.native_execution == "UNSUPPORTED_PENDING_SEPARATE_VALIDATION"
    assert spec.derivation == "DERIVED_FROM_RETAINED_CENSUS"
    assert spec.terraform_cost_gbp is None
    assert spec.cost_category == "terrain-modification"
    assert spec.budgets == dict(BUDGET_LIMITS)


def test_compiled_spec_shape(levelled):
    value, proposal, spec = levelled
    assert [op.op_index for op in spec.ops] == list(range(len(spec.ops)))
    assert all(op.kind == "raise" for op in spec.ops)
    assert all(len(op.corners) == 1 for op in proposal.ops)
    assert {op.before_height for op in spec.ops} == {1}
    assert {op.target_height for op in spec.ops} == {2}
    written = {op.shared_point for op in spec.ops}
    assert len(written) == len(spec.ops)
    assert spec.corner_op_count == len(spec.ops)
    assert not set(spec.region_tiles) & set(spec.halo_tiles)
    assert spec.observation_tiles == tuple(sorted(set(spec.region_tiles) | set(spec.halo_tiles)))
    for op in spec.ops:
        px, py = op.shared_point
        sharing = tuple(
            sorted(
                tile.tile_id
                for tile in value.facts.tiles
                if px - 1 <= tile.x <= px and py - 1 <= tile.y <= py
            )
        )
        assert op.sharing_tiles == sharing
        assert op.native_command == "GSTile.RaiseTile"
        # One moved corner per sharing tile, exactly one step apart.
        for shift in op.shifts:
            after = shift.after_corner_heights
            assert max(after.values()) - min(after.values()) <= 1
        moved = [
            (shift.tile_id, shift.corner)
            for shift in op.shifts
            if shift.after_corner_heights[shift.corner] - shift.before_corner_heights[shift.corner]
            == 1
        ]
        assert len(moved) == 4


def test_mask_and_watch_points_of_the_first_raise(levelled):
    _value, _proposal, spec = levelled
    first = spec.ops[0]
    assert first.tile_id == WALL_NORTH_HOST
    assert first.corner == "S" and first.corner_mask == 0x2
    assert first.shared_point == (10, 11)
    assert first.sharing_tiles == (WALL_NORTH_HOST, WALL, 713, 714)
    assert first.edge_watch_points == ((11, 11), (9, 11), (10, 12), (10, 10))


def test_intent_expectation_bridge_of_the_clean_spec(levelled):
    value, _proposal, spec = levelled
    for index, op in enumerate(spec.ops):
        bridge = intent_expectation(spec, index, value.facts)
        assert not hasattr(bridge, "code"), (index, bridge.code, bridge.detail)
        assert bridge.host_tile == op.tile_id
        assert (bridge.corner, bridge.corner_mask, bridge.direction) == (
            op.corner,
            op.corner_mask,
            op.direction,
        )
        assert (bridge.shared_point_x, bridge.shared_point_y) == op.shared_point
        assert bridge.sharing_tiles == op.sharing_tiles
        states = {state.tile: state for state in bridge.tiles}
        assert set(states) == set(bridge.sharing_tiles)
        assert states[op.tile_id].corner == op.corner
        assert states[op.tile_id].before_min_height == op.before_height


def test_intent_expectation_rejects_clear_ops(tree_plan):
    value, _proposal, spec = tree_plan
    clear = next(op for op in spec.ops if op.kind == "clear")
    bridge = intent_expectation(spec, clear.op_index, value.facts)
    assert bridge.code == TerraformSpecCode.UNSUPPORTED_CLEAR_TARGET
    assert "cleaning contract" in bridge.detail


def test_intent_expectation_rejects_out_of_range_index(levelled):
    value, _proposal, spec = levelled
    bridge = intent_expectation(spec, len(spec.ops), value.facts)
    assert bridge.code == TerraformSpecCode.UNSUPPORTED_GEOMETRY
    assert "outside the compiled specification" in bridge.detail


# ---------------------------------------------------------------------------
# Sealed retained census (Seed 17): the pinned 18-operation inventory
# ---------------------------------------------------------------------------


PINNED_PROPOSAL_DIGEST = "4d698a9d748922efac8041af909428cd91d3c26409e30f2e698c62dfef8d644c"
PINNED_SPEC_DIGEST = "9e70b3609a2339299d0fb501ba1c8ba2c6808a8d0ec6c3966124367a075a0d1d"

# The compiler hoists the two D2 clearing ceremonies ahead of every corner
# write (a corner write demands its host and all sharing tiles classified
# clear at admit time), so the canonical execution order is CC then the
# sixteen S-corner raises in the proposal's own (tile, kind, corner) order.
PINNED_KINDS = "CC" + "R" * 16
PINNED_CLEAR_TILES = (45999, 49326)
PINNED_FINAL_SLOPES = {
    48558: (0x09, 0x0B, {"N": 2, "E": 1, "W": 2, "S": 2}),
    48559: (0x09, 0x00, {"N": 2, "E": 2, "W": 2, "S": 2}),
    48814: (0x00, 0x03, {"N": 1, "E": 1, "W": 2, "S": 2}),
    48815: (0x00, 0x00, {"N": 2, "E": 2, "W": 2, "S": 2}),
    50351: (0x00, 0x00, {"N": 2, "E": 2, "W": 2, "S": 2}),
}


@lru_cache(maxsize=1)
def retained():
    from app.planning.p08_v2_snapshot import _load_census, build_v2_snapshot_assessment

    assessment = build_v2_snapshot_assessment(RETAINED, CANDIDATE, project_root=REPO)
    retained_facts, census, bracket, _pages = _load_census(RETAINED, CANDIDATE)
    doc = SupplementalPlanningFacts(
        schema_version=1,
        transport_mode="road",
        source=retained_facts.source,
        region=retained_facts.region,
        settings=retained_facts.settings,
        road=retained_facts.road,
        tiles=tuple(tile.fact() for tile in census.values()),
        coverage_scopes=(),
        coverage=(),
        engines=(),
        capture_economy_date_before=bracket[0],
        capture_economy_date_after=bracket[1],
    )
    return assessment, doc


requires_retained = pytest.mark.skipif(
    not RETAINED.is_file() or not (CANDIDATE / "classification-p000-response.json").is_file(),
    reason="sealed retained artifacts are absent from this checkout",
)


@requires_retained
def test_retained_proposal_digest_is_unchanged():
    assessment, _doc = retained()
    assert assessment.levelling.digest == PINNED_PROPOSAL_DIGEST


@requires_retained
def test_retained_specification_pins_the_reviewed_inventory():
    assessment, doc = retained()
    spec = compile_terraform_spec(assessment.levelling, doc)
    assert not hasattr(spec, "code"), (spec.code, spec.detail)
    assert spec.digest == PINNED_SPEC_DIGEST
    assert (spec.corner_op_count, spec.clearing_op_count, len(spec.ops)) == (16, 2, 18)
    assert len(spec.corridor) == 24
    assert spec.interior_road_tiles == 22
    assert (len(spec.region_tiles), len(spec.halo_tiles)) == (43, 53)
    assert len(spec.observation_tiles) == 96
    assert (spec.target_height, spec.pickup_stop, spec.delivery_stop) == (2, 45748, 50351)
    assert spec.budgets == dict(BUDGET_LIMITS)


@requires_retained
def test_retained_specification_is_deterministic():
    assessment, doc = retained()
    first = compile_terraform_spec(assessment.levelling, doc)
    second = compile_terraform_spec(assessment.levelling, doc)
    assert first == second


@requires_retained
def test_retained_final_region_slopes():
    assessment, doc = retained()
    spec = compile_terraform_spec(assessment.levelling, doc)
    final = {shift.tile_id: shift for shift in spec.final_region_tiles}
    assert len(final) == 43
    for tile_id, (before_slope, after_slope, corners) in PINNED_FINAL_SLOPES.items():
        shift = final[tile_id]
        assert shift.before_slope == before_slope, tile_id
        assert shift.after_slope == after_slope, tile_id
        assert shift.after_corner_heights == corners, tile_id


@requires_retained
def test_retained_operation_inventory():
    assessment, doc = retained()
    spec = compile_terraform_spec(assessment.levelling, doc)
    ops = spec.ops
    kinds = "".join(op.kind[0].upper() for op in ops)
    assert kinds == PINNED_KINDS
    assert [op.tile_id for op in ops if op.kind == "clear"] == list(PINNED_CLEAR_TILES)
    assert (ops[0].before_height, ops[0].target_height) == (2, 2)
    raises = [op for op in ops if op.kind != "clear"]
    # Exactly one S corner per raise, one step, from 1 to 2, never written twice.
    assert {op.corner for op in raises} == {"S"}
    assert {op.corner_mask for op in raises} == {0x2}
    assert {op.direction for op in raises} == {"up"}
    assert {(op.before_height, op.target_height) for op in raises} == {(1, 2)}
    written = [op.shared_point for op in raises]
    assert len(written) == len(set(written)) == 16
    assert len({op.tile_id for op in raises}) == 16
    assert all(op.native_command == "GSTile.RaiseTile" for op in raises)
    # The second clear (49326) is the raise host's prerequisite (pinned op 7/8).
    # The 49326 tree clear is bound to the raise on its own tile and to the
    # raise at 49070, whose shared point (175,192) is observed by 49326.
    bound = {
        op.tile_id: op.required_earlier_clearings for op in raises if op.required_earlier_clearings
    }
    assert bound == {49070: (1,), 49326: (1,)}
    assert all(op.required_earlier_clearings == () for op in raises if op.tile_id not in bound)


@requires_retained
def test_retained_intent_bridges():
    assessment, doc = retained()
    spec = compile_terraform_spec(assessment.levelling, doc)
    for index, op in enumerate(spec.ops):
        bridge = intent_expectation(spec, index, doc)
        if op.kind == "clear":
            assert bridge.code == TerraformSpecCode.UNSUPPORTED_CLEAR_TARGET
            assert "cleaning contract" in bridge.detail
            continue
        assert not hasattr(bridge, "code"), (index, bridge.code, bridge.detail)
    bridge_one = intent_expectation(spec, 2, doc)
    assert (bridge_one.host_tile, bridge_one.corner_mask) == (48558, 0x2)
    assert (bridge_one.shared_point_x, bridge_one.shared_point_y) == (175, 190)
    assert bridge_one.sharing_tiles == (48558, 48559, 48814, 48815)
    bridge_eight = intent_expectation(spec, 8, doc)
    assert bridge_eight.host_tile == 49326
    assert bridge_eight.corner_mask == 0x2
    assert (bridge_eight.shared_point_x, bridge_eight.shared_point_y) == (175, 193)
    assert bridge_eight.sharing_tiles == (49326, 49327, 49582, 49583)
    for bridge in (bridge_one, bridge_eight):
        states = {state.tile: state for state in bridge.tiles}
        assert set(states) == set(bridge.sharing_tiles)
        assert states[bridge.host_tile].corner == "S"
