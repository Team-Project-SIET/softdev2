"""Bounded terrain-aware P08 routing: complete reachability, detours, Seed 17 replay.

Offline only: no OpenTTD launch, no AdminPort connection and no native
authorization use. Retained-evidence tests skip when the ignored artifacts are
absent from this checkout and never mutate them.
"""

import json
from collections import deque
from pathlib import Path

import pytest
from test_p08_controlled_road import (  # noqa: F401
    POLICY,
    generated,
    mapped,
    region_facts,
    world_for,
)

from app.planning.canonical import scenario_hash
from app.planning.optimizer import optimize_candidate_network
from app.planning.p08_adapter import MAX_PATH_EXPANSIONS, MAX_STATIONS_PER_ROLE
from app.planning.p08_road import (
    ControlledRoadScenario,
    NoRoadScenario,
    corridor_reachability,
    find_depot,
    shortest_path,
    vacant,
    witness_order,
)
from app.planning.validation import validate_execution_plan
from app.simulation.openttd.supplemental_planning_facts import SupplementalPlanningFacts

SEED17_RUN = Path("artifacts/demos/playable-demo-698799a2dfb146948fd2983ff2032253")
FIXED_DEMO_RUN = Path("artifacts/demos/playable-demo-25d891bc9f3444aca73058165d10055a")


@pytest.fixture(scope="module")
def world():
    return world_for(accepts=(1,))


def block(d, predicate, field, value=True):
    for t in d["tiles"]:
        if predicate(t):
            t[field] = value


def restrict_delivery(d, tiles_xy):
    for c in d["coverage"]:
        tile = next(t for t in d["tiles"] if t["tile_id"] == c["tile_id"])
        if c["role"] == "pickup":
            c["industry_covered"] = (tile["x"], tile["y"]) == (0, 1)
        else:
            c["industry_covered"] = (tile["x"], tile["y"]) in set(tiles_xy)


def corridor_adjacent(road: ControlledRoadScenario):
    tiles = {t.tile_id: t for t in road.input.facts.tiles}
    for a, b in zip(road.corridor, road.corridor[1:]):
        ta, tb = tiles[a], tiles[b]
        assert abs(ta.x - tb.x) + abs(ta.y - tb.y) == 1
        assert ta.min_height == tb.min_height
        assert vacant(ta) and vacant(tb)


def eligible_stops(facts, cargo_id, role, *, limit=MAX_STATIONS_PER_ROLE):
    """Same eligibility rule as `station_tiles`, computed from facts alone."""
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
    eligible = [t for t in facts.tiles if t.tile_id in covered and vacant(t)]
    eligible.sort(key=lambda t: t.tile_id)
    return tuple(t.tile_id for t in eligible[:limit]), {
        t.tile_id: t for t in facts.tiles if vacant(t)
    }


def retained_facts(directory: Path, name="network-facts-0.json"):
    return SupplementalPlanningFacts.model_validate_json((directory / name).read_bytes())


def test_detour_around_single_obstacle(world):
    d = region_facts(world, width=6, height=3)
    block(d, lambda t: (t["x"], t["y"]) == (3, 1), "water")
    r = generated(world, d)
    assert isinstance(r, ControlledRoadScenario)
    occupied = next(t for t in r.input.facts.tiles if (t.x, t.y) == (3, 1))
    assert occupied.tile_id not in r.corridor
    corridor_adjacent(r)
    assert len(r.corridor) == 8  # blocked direct 6-tile line forces a single-row detour


def test_multiple_turns_are_supported(world):
    d = region_facts(world, width=6, height=3)
    block(d, lambda t: t["y"] == 1 and 2 <= t["x"] <= 4, "water")
    r = generated(world, d)
    assert isinstance(r, ControlledRoadScenario)
    tiles = {t.tile_id: t for t in r.input.facts.tiles}
    turns = sum(
        1
        for a, b, c in zip(r.corridor, r.corridor[1:], r.corridor[2:])
        if (tiles[b].x - tiles[a].x, tiles[b].y - tiles[a].y)
        != (tiles[c].x - tiles[b].x, tiles[c].y - tiles[b].y)
    )
    assert turns >= 2
    corridor_adjacent(r)


def test_unsupported_terrain_disconnect_is_a_complete_proof(world):
    d = region_facts(world, width=8, height=3)
    block(d, lambda t: t["x"] == 3, "water")
    r = generated(world, d)
    assert isinstance(r, NoRoadScenario) and r.code.value == "NO_BOUNDED_CORRIDOR"
    reason = f"{r.code}: {r.detail}"
    # The retained rejection reason must state the complete eligible-stop
    # search, not merely that the first four stops per role were tried.
    assert "bounded corridor search exhausted" in reason
    assert "eligible pickup and" in reason and "eligible blast" not in reason
    assert "delivery stops are disconnected across all supported corridor tiles" in reason


@pytest.mark.parametrize("barrier", ["slope", "min_height"])
def test_slope_and_height_stepping_stay_unsupported(world, barrier):
    d = region_facts(world, width=8, height=3)
    block(d, lambda t: t["x"] == 3, barrier, 2 if barrier == "min_height" else 1)
    r = generated(world, d)
    assert isinstance(r, NoRoadScenario) and r.code.value == "NO_BOUNDED_CORRIDOR"


def test_route_never_leaves_the_captured_tile_facts(world):
    d = region_facts(world, width=4, height=3)
    block(d, lambda t: t["x"] == 2, "water")
    r = generated(world, d)
    assert isinstance(r, NoRoadScenario) and r.code.value == "NO_BOUNDED_CORRIDOR"
    # Missing neighbour facts (outside the bounded capture) are never members
    # of `tiles`, so `neighbors` cannot yield them: a corridor over unobserved
    # tiles is impossible by construction. The only detour around a full column
    # would exit the captured slice, hence NO_BOUNDED_CORRIDOR.
    tiles = {t.tile_id: t for t in r.input.facts.tiles}
    region_ids = {t["tile_id"] for t in d["tiles"]}
    assert set(tiles) <= region_ids


def test_water_and_industry_tiles_cannot_host_corridors(world):
    d = region_facts(world, width=6, height=3)
    block(d, lambda t: (t["x"], t["y"]) == (2, 1), "industry_id", 2)
    r = generated(world, d)
    assert isinstance(r, ControlledRoadScenario)
    indexed = {t.tile_id: t for t in r.input.facts.tiles}
    assert all(indexed[i].industry_id is None for i in r.corridor)
    d = region_facts(world, width=6, height=3)
    block(d, lambda t: t["x"] == 3, "industry_id", 2)
    r = generated(world, d)
    assert isinstance(r, NoRoadScenario) and r.code.value == "NO_BOUNDED_CORRIDOR"


def test_missing_catchment_still_precedes_corridor_search(world):
    d = region_facts(world, width=6, height=3)
    for c in d["coverage"]:
        c["industry_covered"] = False
    r = generated(world, d)
    assert isinstance(r, NoRoadScenario)
    assert str(r.code) in ("MISSING_CATCHMENT", "NO_STATION_PLACEMENT")


def test_witness_fallback_recovers_a_beyond_four_stop_pair(world):
    """Beyond-first-four witnesses recover a feasible pair the incumbent missed.

    Deliveries (8..11, 1) sit behind a full water column at x=6 and are the four
    nearest stops to the acceptor anchor, so every incumbent pair is
    disconnected. The fifth-eligible delivery (5, 1) is on the reachable side;
    without the witness fallback this scenario reported NO_BOUNDED_CORRIDOR.
    """
    d = region_facts(world, width=12, height=3)
    block(d, lambda t: t["x"] == 6, "water")
    restrict_delivery(d, {(8, 1), (9, 1), (10, 1), (11, 1), (5, 1)})
    r = generated(world, d)
    assert isinstance(r, ControlledRoadScenario), r
    assert len(r.corridor) == 6  # (0,1) .. (5,1): the admissible four interior tiles
    corridor_adjacent(r)
    assert r.depot.tile_id not in r.corridor and r.depot.front_tile_id in r.corridor[1:-1]
    assert r.station_pairs_examined <= 16
    assert scenario_hash(r.scenario) == scenario_hash(generated(world, d).scenario)
    solution = optimize_candidate_network(r.scenario)
    validate_execution_plan(solution.plan, r.scenario)
    assert solution.plan.routes


def test_rejection_reason_flows_to_planning_diagnostics(world):
    """The pipeline records `str(code) + ': ' + detail`; keep that composition stable."""
    d = region_facts(world, width=8, height=3)
    block(d, lambda t: t["x"] == 3, "water")
    r = generated(world, d)
    assert isinstance(r, NoRoadScenario)
    reason = f"{r.code}: {r.detail}"
    assert reason.startswith("NO_BOUNDED_CORRIDOR: bounded corridor search exhausted")
    # The random diagnostic limitations must keep describing the supported model
    # truthfully: the extension stays within flat vacant land only.
    source = Path("app/demo_random.py").read_text()
    for phrase in (
        "flat vacant land only; no clearing, slopes, bridges or tunnels",
        "native executor requires 2..47 road tiles and independent admission",
    ):
        assert phrase in source


def test_witness_order_prefers_supported_2_47_corridors():
    over_long = tuple(range(1, 53))  # 50 interior road tiles
    detour = (100, 101, 102, 103, 104, 105, 106)  # 5 interior tiles
    minimum = (200, 201, 202, 203)  # 2 interior tiles: supported minimum
    ordered = witness_order({7: minimum, 9: over_long, 8: detour})
    assert ordered[0] == minimum
    assert ordered[1] == detour
    assert ordered[-1] == over_long


def test_reachability_oracle_is_deterministic_and_uniform_cost(world):
    m = mapped(world)
    tiles = {t.tile_id: t for t in m.facts.tiles if vacant(t)}
    pickups, _ = eligible_stops(m.facts, 1, "pickup")
    deliveries, _ = eligible_stops(m.facts, 1, "delivery")
    first, first_expansions, first_exhausted = corridor_reachability(
        pickups, deliveries, tiles, m.manifest.width_tiles, budget=MAX_PATH_EXPANSIONS
    )
    second, second_expansions, second_exhausted = corridor_reachability(
        tuple(reversed(pickups)),
        tuple(reversed(deliveries)),
        dict(reversed(list(tiles.items()))),
        m.manifest.width_tiles,
        budget=MAX_PATH_EXPANSIONS,
    )
    assert first == second
    assert first_expansions == second_expansions
    assert not first_exhausted and not second_exhausted


def test_reachability_budget_exhaustion_fails_closed(world):
    m = mapped(world)
    tiles = {t.tile_id: t for t in m.facts.tiles if vacant(t)}
    pickups, _ = eligible_stops(m.facts, 1, "pickup")
    deliveries, _ = eligible_stops(m.facts, 1, "delivery")
    witnesses, expansions, exhausted = corridor_reachability(
        pickups, deliveries, tiles, m.manifest.width_tiles, budget=0
    )
    assert exhausted and witnesses == {}


@pytest.mark.parametrize("cap", [1, 3])
def test_search_budget_exhaustion_is_typed_and_fail_closed(world, monkeypatch, cap):
    """The reachability oracle and the pair selection share the expansion bound."""
    import app.planning.p08_road as module

    monkeypatch.setattr(module, "MAX_PATH_EXPANSIONS", cap)
    r = generated(world)
    assert isinstance(r, NoRoadScenario) and r.code.value == "SEARCH_LIMIT_EXCEEDED"


def test_seed17_retained_observation_replay():
    """Replay the retained native 450-tile coal rectangle through the routing layer.

    This is a retained-evidence replay of P08's supported corridor model: the
    immutable native facts decide the outcome. No native run happens here.
    """
    if not SEED17_RUN.exists():
        pytest.skip("optional retained Seed 17 native smoke evidence is not installed")
    facts = retained_facts(SEED17_RUN)
    assert facts.region.width * facts.region.height == 450
    vacant_tiles = {t.tile_id: t for t in facts.tiles if vacant(t)}
    assert len(vacant_tiles) == 339
    kinds = {"water": 0, "tree": 0, "industry": 0, "rough": 0, "steep_slope": 0}
    for t in facts.tiles:
        if vacant(t):
            continue
        if t.industry_id is not None:
            kinds["industry"] += 1
        elif t.water:
            kinds["water"] += 1
        elif t.tree:
            kinds["tree"] += 1
        elif t.rough:
            kinds["rough"] += 1
        else:
            kinds["steep_slope"] += 1
    assert kinds == {"water": 17, "tree": 50, "industry": 12, "rough": 13, "steep_slope": 19}
    (pickups, _), (deliveries, _) = (
        eligible_stops(facts, 1, "pickup", limit=None),
        eligible_stops(facts, 1, "delivery", limit=None),
    )
    assert len(pickups) == 31 and len(deliveries) == 20
    assert set(pickups) | set(deliveries) <= set(vacant_tiles)
    witnesses, expansions, exhausted = corridor_reachability(
        pickups, deliveries, vacant_tiles, facts.source.map_width, budget=MAX_PATH_EXPANSIONS
    )
    assert not exhausted and expansions <= MAX_PATH_EXPANSIONS
    witnesses = {z: p for z, p in witnesses.items() if p[0] != z}
    # Complete supported-graph result: no corridor exists between the two
    # catchments, so the retained NO_BOUNDED_CORRIDOR is a proven outcome and
    # not a first-four-stop search artifact.
    assert witnesses == {}
    # Phase C classification evidence, derived from the retained native facts:
    # tree clearing alone (strict supported height semantics) does not connect
    # the catchments; only crossing the natively non-buildable steep-slope
    # escarpment would, which presumes terrain levelling. No levelling
    # operation exists in the verified OpenTTD 15.3 GameScript API surface.
    facts_tiles = {t.tile_id: t for t in facts.tiles}

    graph = {
        t.tile_id: t
        for t in facts.tiles
        if t.slope == 0
        and t.industry_id is None
        and not t.water
        and not t.coast
        and not t.rock
        and not t.farm
        and not t.rough
    } | {t.tile_id: t for t in facts.tiles if t.tree}
    found, _, _ = corridor_reachability(
        pickups, deliveries, graph, facts.source.map_width, budget=4096
    )
    found = {z: p for z, p in found.items() if p[0] != z}
    assert found == {}  # tree clearing alone never produces a supported corridor

    # Optimistic levelling lower bound: relax the supported equal-height rule
    # and allow passage over the non-buildable steep-slope escarpment,
    # presuming the land is levelled first. The retained facts still bound the
    # required detour from above.
    def levelling(t):
        return (
            t.industry_id is None and not t.water and not t.rough and not (t.tree and t.slope == 0)
        )

    relaxed = {t.tile_id: t for t in facts.tiles if levelling(t)}
    assert set(relaxed) >= set(pickups) | set(deliveries)
    best = None
    for origin in pickups:
        parents = {origin: None}
        frontier = deque([origin])
        while frontier:
            current = frontier.popleft()
            tile = facts_tiles[current]
            for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
                n = facts_tiles.get((tile.y + dy) * facts.source.map_width + tile.x + dx)
                if n is not None and n.tile_id in relaxed and n.tile_id not in parents:
                    parents[n.tile_id] = current
                    frontier.append(n.tile_id)
        for target in deliveries:
            if target not in parents or target == origin:
                continue
            route = [target]
            while parents[route[-1]] is not None:
                route.append(parents[route[-1]])
            route.reverse()
            if best is None or len(route) < len(best):
                best = tuple(route)
    assert best is not None and 4 <= len(best) <= 49


def test_fixed_demo_retained_corridor_regression():
    """The incumbent selection must keep reproducing the consumed fixed-demo plan.

    Uses the real `vacant`/`shortest_path`/`find_depot` functions over the
    retained native facts and asserts the selected corridor equals the frozen
    planning scenario's corridor for the same relationship.
    """
    if not FIXED_DEMO_RUN.exists():
        pytest.skip("optional retained fixed-demo native evidence is not installed")
    scenario = json.loads((FIXED_DEMO_RUN / "planning-scenario.json").read_bytes())
    anchors = {
        int(loc["location_id"].split("-")[1]): (loc["tile"]["x"], loc["tile"]["y"])
        for loc in scenario["locations"]
        if loc["location_id"].startswith("industry-")
    }
    frozen = {
        c["origin_id"]: [(t["x"], t["y"]) for t in c["tiles"]]
        for c in scenario["infrastructure_candidates"]
        if c["kind"] == "segment"
    }
    for index in range(3):
        facts = retained_facts(FIXED_DEMO_RUN, f"network-facts-{index}.json")
        width = facts.source.map_width
        tiles = {t.tile_id: t for t in facts.tiles if vacant(t)}
        scope = {s.role: s for s in facts.coverage_scopes}
        stops = {}
        for role in ("pickup", "delivery"):
            s = scope[role]
            covered = {
                c.tile_id
                for c in facts.coverage
                if c.industry_id == s.industry_id
                and c.cargo_id == s.cargo_id
                and c.role == role
                and c.industry_covered
                and (c.producer_count > 0 if role == "pickup" else c.acceptance_eighths >= 8)
            }
            eligible = [t for t in facts.tiles if t.tile_id in covered and vacant(t)]
            eligible.sort(
                key=lambda t: (
                    abs(t.x - anchors[s.industry_id][0]) + abs(t.y - anchors[s.industry_id][1]),
                    t.tile_id,
                )
            )
            stops[role] = tuple(t.tile_id for t in eligible[:MAX_STATIONS_PER_ROLE])
        chosen = None
        for a in stops["pickup"]:
            for z in stops["delivery"]:
                if a == z:
                    continue
                path, _ = shortest_path(a, z, tiles, width)
                if len(path) >= 3 and find_depot(path, tiles, width) is not None:
                    chosen = path
                    break
            if chosen:
                break
        assert chosen is not None
        expected = frozen[f"pickup-{chosen[0]}"]
        assert [(tiles[t].x, tiles[t].y) for t in chosen] == expected
