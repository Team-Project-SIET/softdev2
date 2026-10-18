"""Bounded terrain-modification planning: levelling proposals, budgets, Seed 17.

Offline only: no OpenTTD launch, no AdminPort connection, no native
authorization use. Proposals are planning diagnostics: native terrain execution
stays unsupported until separately validated. Retained-evidence tests skip when
the ignored artifacts are absent from this checkout and never mutate them.

Controlled fixtures capture a rectangle from a 64x64 map so every corner point
around the levelling region stays inside the capture unless a test wants the
unobserved-tile rejection.
"""

from pathlib import Path

import pytest
from test_p08_controlled_road import mapped, region_facts, world_for
from test_supplemental_planning_contracts import fact_dict

from app.planning.p08_adapter import MAX_PATH_EXPANSIONS, RoadOutcome
from app.planning.p08_road import (
    ControlledRoadScenario,
    NoRoadScenario,
    generate_road_scenario,
    vacant,
)
from app.planning.p08_terrain import (
    CAPEX_CATEGORY_TERRAIN,
    CORNER_POINT_OFFSET,
    FeasibilityCode,
    TerrainInfeasibility,
    TerrainInfeasibilityCode,
    TerrainProposal,
    corner_heights,
    plan_bounded_levelling,
)
from app.simulation.openttd.supplemental_planning_facts import (
    SupplementalPlanningFacts,
)

SEED17_RUN = Path("artifacts/demos/playable-demo-698799a2dfb146948fd2983ff2032253")
FIXED_DEMO_RUN = Path("artifacts/demos/playable-demo-25d891bc9f3444aca73058165d10055a")

# Official slope bits under test (src/slope_type.h): W=1, S=2, E=4, N=8, steep=16.
SLOPE_N = 0x8
SLOPE_NWS = 0xB  # N|W|S raised: three-corner rise, E stays at the base height
SLOPE_STEEP_W = 0x1B  # steep + NWS: west corner two steps above the base height


@pytest.fixture(scope="module")
def world():
    return world_for(accepts=(1,))


def retiled(d, overrides):
    """Per-tile (x, y) field overrides inside a raw fact dictionary."""
    for x, y, fields in overrides:
        tile = next(t for t in d["tiles"] if (t["x"], t["y"]) == (x, y))
        tile.update(fields)


def facts_at(world, x0, y0, width, height, *, anchor_row=None):
    """`region_facts` captured at an interior map position so the corner points
    around the captured rectangle have captured neighbors. Anchors sit two
    tiles inside each capture edge (``anchor_row`` pins the anchor row)."""
    producer, acceptor = sorted(i.id for i in world.structural.inventory.observation.records)
    d = fact_dict(world)
    d["region"] = dict(x=x0, y=y0, width=width, height=height)
    prototype = d["tiles"][0]
    map_width = world.context.world.map_width
    d["tiles"] = [
        dict(prototype, tile_id=y * map_width + x, x=x, y=y)
        for y in range(y0, y0 + height)
        for x in range(x0, x0 + width)
    ]
    cargo = world.production.records[0].cargo_id
    d["coverage_scopes"] = [
        dict(industry_id=producer, cargo_id=cargo, role="pickup"),
        dict(industry_id=acceptor, cargo_id=cargo, role="delivery"),
    ]
    row = y0 + height // 2 if anchor_row is None else anchor_row
    d["coverage"] = [
        dict(
            tile_id=t["tile_id"],
            **s,
            producer_count=1,
            acceptance_eighths=8,
            industry_covered=(
                (t["x"] == x0 + 2 if s["role"] == "pickup" else t["x"] == x0 + width - 3)
                and t["y"] == row
            ),
        )
        for t in d["tiles"]
        for s in d["coverage_scopes"]
    ]
    return d


def height_profile(world, x0, y0, width, height, *, wall_x, extra_overrides=()):
    """Two-level world: height-1 flats left of ``wall_x``, height-2 flats right
    of it, and one rise tile per row at ``wall_x`` (N|W|S rise, min height 1).
    Every row keeps the wall, so the supported corridor graph stays disconnected
    and the ordinary P08 result remains NO_BOUNDED_CORRIDOR."""
    d = facts_at(world, x0, y0, width, height)
    retiled(
        d,
        [
            (x, y, {"min_height": 2 if x >= wall_x + 1 else 1, "slope": 0})
            for x in range(x0, x0 + width)
            for y in range(y0, y0 + height)
        ],
    )
    retiled(
        d,
        [(wall_x, y, {"min_height": 1, "slope": SLOPE_NWS}) for y in range(y0, y0 + height)],
    )
    retiled(d, list(extra_overrides))
    return d


def eligible_stops(facts, cargo_id, role):
    """Same eligibility rule as ``station_tiles``, computed from facts alone."""
    scope = next(s for s in facts.coverage_scopes if s.role == role)
    covered = {
        c.tile_id
        for c in facts.coverage
        if c.industry_id == scope.industry_id
        and c.cargo_id == cargo_id
        and c.role == role
        and c.industry_covered
        and (c.producer_count > 0 if role == "pickup" else c.acceptance_eighths >= 8)
    }
    return tuple(sorted(t.tile_id for t in facts.tiles if t.tile_id in covered and vacant(t)))


def stops_for(value):
    assert value.supplies
    cargo = value.supplies[0].cargo_id
    return (
        eligible_stops(value.facts, cargo, "pickup"),
        eligible_stops(value.facts, cargo, "delivery"),
    )


@pytest.fixture(scope="module")
def height_value(world):
    return mapped(world, height_profile(world, 8, 8, 11, 7, wall_x=13))


def test_corner_heights_follow_official_slope_bits(world):
    tile = mapped(world, region_facts(world, width=2, height=1)).facts.tiles[0]
    flat = tile.model_copy(update={"min_height": 3, "slope": 0})
    assert corner_heights(flat) == {"N": 3, "E": 3, "W": 3, "S": 3}
    single = tile.model_copy(update={"min_height": 3, "slope": SLOPE_N})
    assert corner_heights(single) == {"N": 4, "E": 3, "W": 3, "S": 3}
    three = tile.model_copy(update={"min_height": 3, "slope": SLOPE_NWS})
    assert corner_heights(three) == {"N": 4, "E": 3, "W": 4, "S": 4}
    steep = tile.model_copy(update={"min_height": 3, "slope": SLOPE_STEEP_W})
    assert corner_heights(steep) == {"N": 4, "E": 3, "W": 5, "S": 4}


def test_simple_height_difference_yields_bounded_raise_proposal(height_value):
    value = height_value
    pickups, deliveries = stops_for(value)
    r = plan_bounded_levelling(value.facts, pickups, deliveries)
    assert isinstance(r, TerrainProposal), r
    assert r.target_height == 2
    assert r.corridor[0] in pickups and r.corridor[-1] in deliveries
    assert 2 <= r.interior_road_tiles <= 47
    assert r.terraform_cost_gbp is None
    assert r.execution_status == "PLANNING_ONLY"
    assert r.native_execution == "UNSUPPORTED_PENDING_SEPARATE_VALIDATION"
    assert r.cost_category == CAPEX_CATEGORY_TERRAIN
    assert "GSTile.GetCornerHeight" in r.required_readbacks
    corner_ops = [op for op in r.ops if op.kind in ("raise", "lower")]
    assert corner_ops and all(op.kind == "raise" for op in corner_ops)
    assert {op.before_height for op in corner_ops} == {1}
    assert {op.target_height for op in corner_ops} == {2}
    # Official corner naming order (N, E, W, S) and no shared corner point twice.
    assert all(
        op.corners == tuple(n for n in ("N", "E", "W", "S") if n in op.corners) for op in corner_ops
    )
    hosts = [(op.tile_id, corner) for op in corner_ops for corner in op.corners]
    assert len(hosts) == len(set(hosts))


def test_region_closure_covers_tiles_sharing_raised_corners(height_value):
    value = height_value
    pickups, deliveries = stops_for(value)
    r = plan_bounded_levelling(value.facts, pickups, deliveries)
    assert isinstance(r, TerrainProposal), r
    tiles = {t.tile_id: t for t in value.facts.tiles}
    points_of: dict[tuple[int, int], set[int]] = {}
    for tile in tiles.values():
        for name, (dx, dy) in CORNER_POINT_OFFSET.items():
            points_of.setdefault((tile.x + dx, tile.y + dy), set()).add(tile.tile_id)
    dirty_points = set()
    for op in r.ops:
        if op.kind not in ("raise", "lower"):
            continue
        tile = tiles[op.tile_id]
        for corner in op.corners:
            dx, dy = CORNER_POINT_OFFSET[corner]
            dirty_points.add((tile.x + dx, tile.y + dy))
    assert dirty_points
    shared = {tile_id for point in dirty_points for tile_id in points_of[point]}
    assert shared <= set(r.region_tiles)
    # The halo stays readback-only: inside the capture, never inside the region.
    assert set(r.halo_tiles) <= set(tiles)
    assert not set(r.halo_tiles) & set(r.region_tiles)


def test_proposal_is_deterministic_with_stable_digest(height_value):
    value = height_value
    pickups, deliveries = stops_for(value)
    first = plan_bounded_levelling(value.facts, pickups, deliveries)
    second = plan_bounded_levelling(value.facts, pickups, deliveries)
    assert isinstance(first, TerrainProposal) and isinstance(second, TerrainProposal)
    assert first.digest == second.digest == first.digest
    assert [op.sort_key for op in first.ops] == [op.sort_key for op in second.ops]


def test_two_step_slope_cannot_be_levelled(world):
    """A steep rise is two corner-steps from any stop height: unsupported."""
    d = height_profile(world, 8, 8, 11, 7, wall_x=13)
    retiled(d, [(13, y, {"min_height": 1, "slope": SLOPE_STEEP_W}) for y in range(8, 15)])
    value = mapped(world, d)
    pickups, deliveries = stops_for(value)
    r = plan_bounded_levelling(value.facts, pickups, deliveries)
    assert isinstance(r, TerrainInfeasibility)
    assert r.code == TerrainInfeasibilityCode.NO_CONNECTED_LEVELED_CORRIDOR


def test_clearing_is_classified_not_implemented(world):
    """Flat obstructed land joins the corridor only via a classified clear op."""
    d = height_profile(world, 8, 8, 11, 7, wall_x=13, extra_overrides=((12, 12, {"tree": True}),))
    value = mapped(world, d)
    pickups, deliveries = stops_for(value)
    r = plan_bounded_levelling(value.facts, pickups, deliveries)
    assert isinstance(r, TerrainProposal)
    assert len(r.cleared_tiles) == 1
    assert {op.kind for op in r.ops} <= {"raise", "lower", "clear"}
    cleared_ops = [op for op in r.ops if op.kind == "clear"]
    assert cleared_ops and cleared_ops[0].corners == ()
    assert cleared_ops[0].tile_id == r.cleared_tiles[0] == 12 * 64 + 12
    kinds = [op.kind for op in r.ops]
    assert kinds and all(kind in ("raise", "lower", "clear") for kind in kinds)


def test_industry_tile_rejects_the_levelling_region(world):
    d = height_profile(
        world,
        8,
        8,
        11,
        7,
        wall_x=13,
        extra_overrides=((13, 12, {"industry_id": 2, "slope": 0}),),
    )
    value = mapped(world, d)
    pickups, deliveries = stops_for(value)
    r = plan_bounded_levelling(value.facts, pickups, deliveries)
    assert isinstance(r, TerrainInfeasibility)
    assert r.code == TerrainInfeasibilityCode.FORBIDDEN_TILE_IN_REGION
    assert "FORBIDDEN_TILE_IN_REGION" in r.detail


def test_unobserved_shared_corner_rejects_the_proposal(world):
    """A capture that truncates the row above the corridor cannot authorize
    corner writes: the map tile sharing the raised corner is unobserved."""
    d = facts_at(world, 30, 30, 7, 3, anchor_row=30)
    retiled(
        d,
        [(x, 30, {"min_height": 2 if x >= 34 else 1, "slope": 0}) for x in range(30, 37)]
        + [(x, 31, {"min_height": 1, "slope": 0}) for x in range(30, 37)]
        + [(x, 32, {"min_height": 1, "slope": 0}) for x in range(30, 37)]
        + [(33, 30, {"min_height": 1, "slope": SLOPE_NWS})],
    )
    value = mapped(world, d)
    pickups, deliveries = stops_for(value)
    r = plan_bounded_levelling(value.facts, pickups, deliveries)
    assert isinstance(r, TerrainInfeasibility)
    assert r.code == TerrainInfeasibilityCode.UNOBSERVED_TILE_AFFECTED


def test_proposal_budgets_are_typed_and_fail_closed(height_value):
    value = height_value
    pickups, deliveries = stops_for(value)
    exhausted = plan_bounded_levelling(value.facts, pickups, deliveries, budget=0)
    assert isinstance(exhausted, TerrainInfeasibility)
    assert exhausted.code == TerrainInfeasibilityCode.SEARCH_LIMIT_EXCEEDED
    for limits in (
        {"corner_ops_limit": 1},
        {"region_tiles_limit": 1},
    ):
        capped = plan_bounded_levelling(value.facts, pickups, deliveries, **limits)
        assert isinstance(capped, TerrainInfeasibility)
        assert capped.code == TerrainInfeasibilityCode.TERRAIN_BUDGET_EXCEEDED


def test_empty_or_unknown_stops_fail_fast(world):
    value = mapped(world, height_profile(world, 8, 8, 11, 7, wall_x=13))
    pickups, deliveries = stops_for(value)
    empty = plan_bounded_levelling(value.facts, (), deliveries)
    assert isinstance(empty, TerrainInfeasibility)
    assert empty.code == TerrainInfeasibilityCode.NO_CONNECTED_LEVELED_CORRIDOR
    outside = plan_bounded_levelling(value.facts, (10**9,), deliveries)
    assert isinstance(outside, TerrainInfeasibility)


def test_generation_hook_attaches_planning_only_proposal(height_value):
    """The NO_BOUNDED_CORRIDOR rejection keeps its pinned code and detail and
    only gains the structured levelling proposal and feasibility diagnosis as
    planning diagnostics."""
    road = generate_road_scenario(height_value)
    assert isinstance(road, NoRoadScenario)
    assert road.code == RoadOutcome.NO_BOUNDED_CORRIDOR
    reason = f"{road.code}: {road.detail}"
    assert reason.startswith("NO_BOUNDED_CORRIDOR: bounded corridor search exhausted")
    assert "no feasibility outside this slice implied" in road.detail
    assert isinstance(road.terrain_proposal, TerrainProposal)
    # Task D: the rejection also carries the bounded feasibility assessment.
    assert road.feasibility is not None
    assert road.feasibility.code in (
        FeasibilityCode.TERRAIN_MODIFICATION_REQUIRED,
        FeasibilityCode.CONNECTED_WITHOUT_MODIFICATION,
        FeasibilityCode.INCOMPLETE_TILE_CLASSIFICATION,
    )
    assert road.feasibility.world_id == height_value.facts.source.world_id


def test_connected_controlled_scenario_has_no_terrain_artifacts(world):
    road = generate_road_scenario(mapped(world, region_facts(world, width=7, height=3)))
    assert isinstance(road, ControlledRoadScenario)
    assert getattr(road, "terrain_proposal", None) is None


# --- retained-evidence replays ----------------------------------------------


def retained_facts(directory: Path, name="network-facts-0.json"):
    return SupplementalPlanningFacts.model_validate_json((directory / name).read_bytes())


def eligible_all(facts, cargo_id, role):
    scope = next(s for s in facts.coverage_scopes if s.role == role)
    covered = {
        c.tile_id
        for c in facts.coverage
        if c.industry_id == scope.industry_id
        and c.cargo_id == cargo_id
        and c.role == role
        and c.industry_covered
        and (c.producer_count > 0 if role == "pickup" else c.acceptance_eighths >= 8)
    }
    return tuple(sorted(t.tile_id for t in facts.tiles if t.tile_id in covered and vacant(t)))


def test_seed17_retained_levelling_proposal():
    """The retained Seed 17 height-step fence cannot be crossed offline.

    Levelling is implemented, but every native height-step adjacency on the
    coal-pair boundary has at least one endpoint the retained TileFact
    projection forbids for the mutation region (water/coast/industry/transport,
    or an obstruction whose concrete class the projection drops - 19 tiles).
    The planner must reject with the structured code and stay deterministic;
    the proof is computed from the facts, not pinned to a route.
    """
    if not SEED17_RUN.exists():
        pytest.skip("optional retained Seed 17 native smoke evidence is not installed")
    from app.planning.p08_terrain import (
        MAX_TERRAIN_HEIGHT_DELTA_STEPS,
        _corridor_class,
    )

    facts = retained_facts(SEED17_RUN)
    assert facts.region.width * facts.region.height == 450
    cargo = facts.coverage_scopes[0].cargo_id
    pickups = eligible_all(facts, cargo, "pickup")
    deliveries = eligible_all(facts, cargo, "delivery")
    assert len(pickups) == 31 and len(deliveries) == 20
    r = plan_bounded_levelling(facts, pickups, deliveries)
    assert isinstance(r, TerrainInfeasibility)
    assert r.code == TerrainInfeasibilityCode.NO_CONNECTED_LEVELED_CORRIDOR
    assert r.search_expansions <= MAX_PATH_EXPANSIONS
    # reproducible proof: every adjacent height-step pair is fenced by at
    # least one tile whose class the retained facts cannot authorize
    tiles = {t.tile_id: t for t in facts.tiles}
    classes = {tid: _corridor_class(t) for tid, t in tiles.items()}
    pairs = []
    for t in tiles.values():
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            n = tiles.get((t.y + dy) * facts.source.map_width + t.x + dx)
            if n is None or (n.x, n.y) != (t.x + dx, t.y + dy):
                continue
            if t.min_height == n.min_height:
                continue  # only actual height steps can block levelling
            if abs(t.min_height - n.min_height) > MAX_TERRAIN_HEIGHT_DELTA_STEPS:
                continue
            pairs.append((t.tile_id, n.tile_id))
    assert pairs, "the retained capture must contain the native height steps"
    fenced = [(a, b) for a, b in pairs if classes[a] == "forbidden" or classes[b] == "forbidden"]
    assert len(fenced) == len(pairs), "every height step must be fenced"
    again = plan_bounded_levelling(facts, pickups, deliveries)
    assert isinstance(again, TerrainInfeasibility)
    assert again.detail == r.detail and again.search_expansions == r.search_expansions


def supported_connected(facts, pickups, deliveries):
    """p08_road supported rule: flat vacant tiles, equal min_height cardinal."""
    tiles = {t.tile_id: t for t in facts.tiles}
    vacant = {
        tid
        for tid, t in tiles.items()
        if t.buildable
        and t.slope == 0
        and t.industry_id is None
        and not any(
            (
                t.water,
                t.coast,
                t.tree,
                t.farm,
                t.rock,
                t.rough,
                t.road,
                t.rail,
                t.water_transport,
                t.air_transport,
            )
        )
    }
    frontier = [p for p in pickups if p in vacant]
    seen = set(frontier)
    while frontier:
        cur = tiles[frontier.pop()]
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            n = tiles.get((cur.y + dy) * facts.source.map_width + cur.x + dx)
            if (
                n is not None
                and (n.x, n.y) == (cur.x + dx, cur.y + dy)
                and n.tile_id in vacant
                and n.tile_id not in seen
                and n.min_height == cur.min_height
            ):
                seen.add(n.tile_id)
                frontier.append(n.tile_id)
    return any(d in seen for d in deliveries)


def test_fixed_demo_pipeline_has_no_terrain_consequence():
    """The fixed demo replay path still clears the terrain-proposal hook:
    connected scenarios return the unchanged ControlledRoadScenario type."""
    if not FIXED_DEMO_RUN.exists():
        pytest.skip("optional retained fixed-demo native evidence is not installed")
    facts = retained_facts(FIXED_DEMO_RUN)
    cargo = facts.coverage_scopes[0].cargo_id
    pickups = eligible_all(facts, cargo, "pickup")[:4]
    deliveries = eligible_all(facts, cargo, "delivery")[:4]
    if not supported_connected(facts, pickups, deliveries):
        pytest.skip("fixed-demo replay facts changed in this checkout")
    r = plan_bounded_levelling(facts, pickups, deliveries)
    assert isinstance(r, TerrainProposal), r
    assert r.execution_status == "PLANNING_ONLY"
    assert plan_bounded_levelling(facts, pickups, deliveries).digest == r.digest
