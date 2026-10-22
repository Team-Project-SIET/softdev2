"""Generalized feasibility classification, construction readiness, diagnostics.

Offline only: retained/controlled evidence, no launch, no connection, no
evidence mutation. Covers Task B (segment classification + assessment),
Task C (construction readiness registry) and Task D (stable diagnostic codes,
world-identity records, pipeline attachment) plus old-evidence compatibility.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from test_p08_bounded_terrain import (  # noqa: E402
    FIXED_DEMO_RUN,
    SEED17_RUN,
    eligible_all,
    height_profile,
    mapped,
    region_facts,
    retained_facts,
    stops_for,
)
from test_p08_controlled_road import world_for  # noqa: E402

from app.planning.construction_readiness import (  # noqa: E402
    CLASSIFIED_CLEAR,
    CORNER_LOWER,
    CORNER_RAISE,
    LEVEL_TILES,
    NATIVE_SUPPORT_PROHIBITED,
    OCCUPANCY_CONVERSION,
    UNKNOWN_TILE,
    blocked_offline,
    readiness_summary,
    requirement_for_op,
    requirement_ids_for_counts,
)
from app.planning.p08_adapter import RoadOutcome  # noqa: E402
from app.planning.p08_road import (  # noqa: E402
    ControlledRoadScenario,
    NoRoadScenario,
    generate_road_scenario,
)
from app.planning.p08_terrain import (  # noqa: E402
    CAPEX_CATEGORY_TERRAIN,
    FeasibilityCode,
    FeasibilityDiagnosis,
    SegmentClass,
    TerrainOp,
    assess_world_feasibility,
    classify_segment,
)
from app.simulation.openttd.supplemental_planning_facts import Region  # noqa: E402
from app.simulation.openttd.tile_classification import (  # noqa: E402
    TileClass,
    TileClassificationIndex,
    TileClassificationRequest,
    TileClassificationResponse,
    tile_classes,
)


def segment_of(tile_fact, tile_class=None):
    return classify_segment(tile_fact, tile_class)[0]


@pytest.fixture(scope="module")
def world():
    return world_for(accepts=(1,))


@pytest.fixture(scope="module")
def height_value(world):
    return mapped(world, height_profile(world, 8, 8, 11, 7, wall_x=13))


def _unclassified_tiles(facts):
    """Tiles whose schema-1 projection dropped their occupancy class."""
    return [
        t
        for t in facts.tiles
        if not t.buildable
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
    ]


def _seed17_stops(facts):
    cargo = facts.coverage_scopes[0].cargo_id
    return eligible_all(facts, cargo, "pickup"), eligible_all(facts, cargo, "delivery")


# --- Task B: segment classification ------------------------------------------


def test_legacy_facts_classify_the_five_segment_classes(world):
    """Legacy projection alone already yields all five segment classes."""
    facts = mapped(world, region_facts(world, width=4, height=2)).facts
    probe = next(
        t
        for t in facts.tiles
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
    )
    assert segment_of(probe) is SegmentClass.ROAD_BUILDABLE
    # Single-field variants over the same projection semantics:
    assert segment_of(probe.model_copy(update={"slope": 8})) is (
        SegmentClass.TERRAIN_MODIFICATION  # sloped clear ground
    )
    assert segment_of(probe.model_copy(update={"tree": True})) is (SegmentClass.SUPPORTED_CLEARING)
    assert segment_of(probe.model_copy(update={"water": True})) is (
        SegmentClass.UNSUPPORTED_CONSTRUCTION
    )
    assert segment_of(probe.model_copy(update={"coast": True})) is (
        SegmentClass.UNSUPPORTED_CONSTRUCTION
    )
    assert segment_of(probe.model_copy(update={"industry_id": 5})) is (
        SegmentClass.UNSUPPORTED_CONSTRUCTION
    )
    # The schema-1 gap: buildable dropped, every projected flag off.
    assert segment_of(probe.model_copy(update={"buildable": False})) is (
        SegmentClass.UNKNOWN_OCCUPANCY
    )
    assert classify_segment(probe, None) == (
        SegmentClass.ROAD_BUILDABLE,
        "vacant-flat-clear",
    )


def test_legacy_projection_dropped_tiles_stay_unknown_not_guessed():
    """The historical schema-1 gap: no occupancy class may be invented."""
    facts = retained_facts(SEED17_RUN)
    dropped = _unclassified_tiles(facts)
    assert len(dropped) == 19
    for tile in dropped:
        assert classify_segment(tile, None) == (
            SegmentClass.UNKNOWN_OCCUPANCY,
            "projection-dropped-occupancy-class",
        )


def test_schema2_classification_maps_occupancy_to_segments(height_value):
    facts = height_value.facts
    probe = facts.tiles[0]
    occupancy = {
        TileClass.HOUSE: SegmentClass.UNSUPPORTED_CONSTRUCTION,
        TileClass.STATION: SegmentClass.UNSUPPORTED_CONSTRUCTION,
        TileClass.INDUSTRY: SegmentClass.UNSUPPORTED_CONSTRUCTION,
        TileClass.WATER: SegmentClass.UNSUPPORTED_CONSTRUCTION,
        TileClass.COAST: SegmentClass.UNSUPPORTED_CONSTRUCTION,
        TileClass.AIRPORT: SegmentClass.UNSUPPORTED_CONSTRUCTION,
        TileClass.ROAD: SegmentClass.UNSUPPORTED_CONSTRUCTION,
        TileClass.RAIL: SegmentClass.UNSUPPORTED_CONSTRUCTION,
        TileClass.DOCK: SegmentClass.UNSUPPORTED_CONSTRUCTION,
        TileClass.TREES: SegmentClass.SUPPORTED_CLEARING,
        TileClass.FARM: SegmentClass.SUPPORTED_CLEARING,
        TileClass.ROCK: SegmentClass.SUPPORTED_CLEARING,
        TileClass.ROUGH: SegmentClass.SUPPORTED_CLEARING,
    }
    for value, want in occupancy.items():
        assert classify_segment(probe, value.value) == (
            want,
            (
                f"classified-occupancy:{value.value}"
                if want is SegmentClass.UNSUPPORTED_CONSTRUCTION
                else f"classified-clearing:{value.value}"
            ),
        )


def test_schema2_clear_refines_by_legacy_shape(height_value):
    value = height_value
    facts = value.facts
    flat = next(t for t in facts.tiles if t.buildable and t.slope == 0 and t.industry_id is None)
    assert classify_segment(flat, "CLEAR") == (SegmentClass.ROAD_BUILDABLE, "classified-clear-flat")
    sloped = next(t for t in facts.tiles if t.buildable and t.slope != 0)
    assert classify_segment(sloped, "CLEAR") == (
        SegmentClass.TERRAIN_MODIFICATION,
        "classified-clear-sloped",
    )
    dropped = next(iter(_unclassified_tiles(facts)), None)
    if dropped is not None:
        # buildable=False contradicts native CLEAR ground: fail explicit.
        assert classify_segment(dropped, "CLEAR") == (
            SegmentClass.UNKNOWN_OCCUPANCY,
            "conflicting-occupancy-evidence",
        )


def test_conflicting_evidence_downgrades_to_unknown(world):
    facts = mapped(world, region_facts(world, width=2, height=1)).facts
    probe = next(t for t in facts.tiles if t.buildable and t.slope == 0 and t.industry_id is None)
    water = probe.model_copy(update={"water": True})
    assert classify_segment(water, "CLEAR") == (
        SegmentClass.UNKNOWN_OCCUPANCY,
        "conflicting-occupancy-evidence",
    )
    # A classified footprint refines (never fights) the projected one.
    assert classify_segment(water, "STATION")[0] is SegmentClass.UNSUPPORTED_CONSTRUCTION
    assert classify_segment(water, None)[0] is SegmentClass.UNSUPPORTED_CONSTRUCTION


def test_unknown_occupancy_value_is_downstreamed_verbatim():
    facts = retained_facts(SEED17_RUN)
    dropped = _unclassified_tiles(facts)
    assert dropped, "the retained capture must contain projection-dropped tiles"
    for tile in dropped:
        assert classify_segment(tile, TileClass.UNKNOWN_OCCUPANCY.value) == (
            SegmentClass.UNKNOWN_OCCUPANCY,
            "no-classifying-predicate",
        )


def test_classification_overlay_does_not_change_planner_budgets(height_value):
    pickups, deliveries = stops_for(height_value)
    without = assess_world_feasibility(height_value.facts, pickups, deliveries)
    with_empty_classes = assess_world_feasibility(
        height_value.facts, pickups, deliveries, tile_classes={}
    )
    assert without.digest == with_empty_classes.digest


def test_projection_coherence_gate_uses_shared_flag_bits(world):
    """Schema-2 masks must project exactly into TileFact or report UNKNOWN."""
    facts = mapped(world, region_facts(world, width=2, height=1)).facts
    probe = next(
        t
        for t in facts.tiles
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
    )

    def flags(*names):
        from app.simulation.openttd.tile_classification import (
            CLASSIFICATION_FLAG_NAMES as order,
        )

        value = 0
        for name in names:
            value |= 1 << order.index(name)
        return value

    # Coherent vacant-clear capture: classification refines cleanly.
    coherent = classify_segment(probe, "CLEAR", flags=flags("buildable"))
    assert coherent == (SegmentClass.ROAD_BUILDABLE, "classified-clear-flat")
    # Native CLEAR claiming a tree where the projection saw none: the
    # same-instant rule fails the tile explicitly.
    assert classify_segment(probe, "CLEAR", flags=flags("buildable", "tree")) == (
        SegmentClass.UNKNOWN_OCCUPANCY,
        "conflicting-occupancy-evidence",
    )
    # A TREES classification over ground the projection says is treeless:
    assert classify_segment(probe, "TREES", flags=flags("tree")) == (
        SegmentClass.UNKNOWN_OCCUPANCY,
        "conflicting-occupancy-evidence",
    )
    # House/station bits legitimately explain the historical buildable=False
    # collapse; the refinement is allowed and stays explicit.
    dropped = probe.model_copy(update={"buildable": False})
    assert classify_segment(dropped, "HOUSE", flags=flags("house")) == (
        SegmentClass.UNSUPPORTED_CONSTRUCTION,
        "classified-occupancy:HOUSE",
    )
    # Native buildable over a projection that dropped it the other way:
    assert classify_segment(dropped, "CLEAR", flags=flags("buildable")) == (
        SegmentClass.UNKNOWN_OCCUPANCY,
        "conflicting-occupancy-evidence",
    )
    # Road bits project through the schema-1 three-way OR.
    road_probe = probe.model_copy(update={"road": True, "buildable": False})
    assert classify_segment(road_probe, "ROAD", flags=flags("road_tile")) == (
        SegmentClass.UNSUPPORTED_CONSTRUCTION,
        "classified-occupancy:ROAD",
    )


def test_assessor_flags_gate_downgrades_conflicting_tiles(height_value):
    value = height_value
    facts = value.facts
    pickups, deliveries = stops_for(value)
    flat = next(
        t
        for t in facts.tiles
        if t.buildable and t.slope == 0 and t.industry_id is None and t.tree is False
    )
    clean = assess_world_feasibility(
        facts, pickups, deliveries, tile_classes={flat.tile_id: "CLEAR"}
    )
    from app.simulation.openttd.tile_classification import CLASSIFICATION_FLAG_NAMES as order

    blocked = assess_world_feasibility(
        facts,
        pickups,
        deliveries,
        tile_classes={flat.tile_id: "CLEAR"},
        tile_flags={flat.tile_id: 1 << order.index("tree")},  # same class, alien mask
    )
    # The conflicted tile cannot silently keep its favorable class: the
    # assessment output must differ from the coherent-capture run.
    assert blocked.digest != clean.digest and blocked.segment_counts != clean.segment_counts


# --- Task D: assessment + diagnostic codes -----------------------------------


def test_seed17_retained_assessment_incomplete_classification():
    facts = retained_facts(SEED17_RUN)
    pickups, deliveries = _seed17_stops(facts)
    diagnosis = assess_world_feasibility(facts, pickups, deliveries)
    assert isinstance(diagnosis, FeasibilityDiagnosis)
    assert diagnosis.code == FeasibilityCode.INCOMPLETE_TILE_CLASSIFICATION
    assert diagnosis.observed_tiles == 450
    counts = dict(diagnosis.segment_counts)
    assert counts[SegmentClass.UNKNOWN_OCCUPANCY.value] == 19
    assert counts[SegmentClass.ROAD_BUILDABLE.value] == 339
    assert counts[SegmentClass.SUPPORTED_CLEARING.value] == 63
    assert diagnosis.budget_exhausted is False and diagnosis.search_expansions > 0
    ops = dict(diagnosis.required_ops)
    assert ops["unknown"] == diagnosis.corridor[-2:] or len(ops["unknown"]) == 2
    assert any(tids for kind, tids in diagnosis.required_ops if kind == "unknown")
    assert diagnosis.world_id == facts.source.world_id
    assert diagnosis.relationship == (("delivery", 1, 1), ("pickup", 0, 1))
    again = assess_world_feasibility(facts, pickups, deliveries)
    assert again.digest == diagnosis.digest and again.corridor == diagnosis.corridor


def test_seed17_with_schema2_house_hypothesis_becomes_unsupported():
    facts = retained_facts(SEED17_RUN)
    classes = {t.tile_id: TileClass.HOUSE.value for t in _unclassified_tiles(facts)}
    pickups, deliveries = _seed17_stops(facts)
    diagnosis = assess_world_feasibility(facts, pickups, deliveries, tile_classes=classes)
    assert diagnosis.code == FeasibilityCode.UNSUPPORTED_CONSTRUCTION
    segment_values = {kind for kind, _count in diagnosis.corridor_segment_counts}
    assert SegmentClass.UNKNOWN_OCCUPANCY.value not in segment_values
    assert SegmentClass.UNSUPPORTED_CONSTRUCTION.value in segment_values


def test_search_budget_exhaustion_reports_explicit_code(height_value):
    pickups, deliveries = stops_for(height_value)
    diagnosis = assess_world_feasibility(height_value.facts, pickups, deliveries, budget=0)
    assert diagnosis.code == FeasibilityCode.SEARCH_BUDGET_EXCEEDED
    assert diagnosis.budget_exhausted is True
    assert diagnosis.corridor == ()
    assert diagnosis.detail == "assessment budget exhausted before the tier completed"


def test_exhausted_mid_assessment_stays_deterministic(height_value):
    """Half-bounded runs report budget codes rather than partial conclusions."""
    value = height_value
    pickups, deliveries = stops_for(value)
    full = assess_world_feasibility(value.facts, pickups, deliveries)
    if full.code == FeasibilityCode.SEARCH_BUDGET_EXCEEDED:
        pytest.skip("controlled world exhausts budget even unbounded")
    for budget in (1, 2, 5):
        squeezed = assess_world_feasibility(value.facts, pickups, deliveries, budget=budget)
        assert squeezed.code in (
            FeasibilityCode.SEARCH_BUDGET_EXCEEDED,
            FeasibilityCode.NO_CONNECTED_CORRIDOR,
            full.code,
        )
    repeat = assess_world_feasibility(
        value.facts, pickups, deliveries, budget=full.search_expansions
    )
    assert repeat.code == full.code


def test_empty_stops_report_no_connection(height_value):
    pickups, deliveries = stops_for(height_value)
    empty = assess_world_feasibility(height_value.facts, (), deliveries)
    assert empty.code == FeasibilityCode.NO_CONNECTED_CORRIDOR
    assert empty.detail == "both eligible stop sets are required"
    assert empty.relationship[0][0] in ("pickup", "delivery")


def test_diagnostics_json_is_stable_and_carries_world_identity():
    facts = retained_facts(SEED17_RUN)
    pickups, deliveries = _seed17_stops(facts)
    diagnosis = assess_world_feasibility(facts, pickups, deliveries)
    payload = diagnosis.as_dict()
    rebuilt = json.loads(json.dumps(payload, sort_keys=True))
    assert rebuilt["world_id"] == facts.source.world_id
    assert rebuilt["map"] == [facts.source.map_width, facts.source.map_height]
    assert rebuilt["region"] == [
        facts.region.x,
        facts.region.y,
        facts.region.width,
        facts.region.height,
    ]
    assert rebuilt["observed_tiles"] == 450
    assert rebuilt["digest"] == diagnosis.digest
    # Diagnostic codes are the additive stable set; no external code renamed.
    assert diagnosis.code in set(
        member for member in vars(FeasibilityCode).values() if isinstance(member, str)
    )


# --- Pipeline attachment (Task D) + P08 compatibility ------------------------


def test_generation_hook_still_pinned_and_gains_feasibility(height_value):
    road = generate_road_scenario(height_value)
    assert isinstance(road, NoRoadScenario)
    assert road.code == RoadOutcome.NO_BOUNDED_CORRIDOR
    assert road.detail.startswith("bounded corridor search exhausted")
    assert road.terrain_proposal is not None
    assert road.feasibility is not None
    assert isinstance(road.feasibility, FeasibilityDiagnosis)
    assert road.feasibility.code in (
        FeasibilityCode.TERRAIN_MODIFICATION_REQUIRED,
        FeasibilityCode.CONNECTED_WITHOUT_MODIFICATION,
        FeasibilityCode.INCOMPLETE_TILE_CLASSIFICATION,
    )
    # The attached diagnosis is the same bounded assessment as standalone.
    pickups, deliveries = stops_for(height_value)
    assert (
        road.feasibility.digest
        == assess_world_feasibility(height_value.facts, pickups, deliveries).digest
    )


def test_connected_scenario_carries_no_rejection_diagnostics(world):
    road = generate_road_scenario(mapped(world, region_facts(world, width=7, height=3)))
    assert isinstance(road, ControlledRoadScenario)
    assert not hasattr(road, "feasibility") or road.feasibility is None


# --- Task C: construction readiness -----------------------------------------


def test_ops_map_to_their_readiness_records():
    assert requirement_for_op(TerrainOp("raise", 714, ("N",), 1, 2)) == CORNER_RAISE.requirement_id
    assert requirement_for_op(TerrainOp("lower", 714, ("S",), 2, 1)) == CORNER_LOWER.requirement_id
    assert requirement_for_op(TerrainOp("clear", 714, (), 1, 1)) == CLASSIFIED_CLEAR.requirement_id
    with pytest.raises(ValueError):
        requirement_for_op(TerrainOp("level", 714, ("N",), 1, 2))


def test_level_tiles_prohibited_and_unknown_out_of_scope():
    assert LEVEL_TILES.native_support == NATIVE_SUPPORT_PROHIBITED
    assert OCCUPANCY_CONVERSION.cost_provenance == "UNKNOWN until observed (never inferred)"
    assert UNKNOWN_TILE.missing_implementation
    assert "schema-2" in UNKNOWN_TILE.preconditions[0]


def test_terrain_requirements_keep_planning_contracts():
    for record in (CORNER_RAISE, CORNER_LOWER, CLASSIFIED_CLEAR):
        assert record.capex_category == CAPEX_CATEGORY_TERRAIN
        assert record.post_command_readbacks
        assert record.cost_provenance and record.partial_failure_risks
    assert readiness_summary("CORNER_RAISE") is CORNER_RAISE
    with pytest.raises(ValueError):
        readiness_summary("BRIDGE_BUILD")


def test_corridor_readiness_ids_follow_segment_counts():
    ids = requirement_ids_for_counts(
        (
            (SegmentClass.ROAD_BUILDABLE.value, 2),
            (SegmentClass.SUPPORTED_CLEARING.value, 1),
            (SegmentClass.TERRAIN_MODIFICATION.value, 3),
            (SegmentClass.UNSUPPORTED_CONSTRUCTION.value, 0),
            (SegmentClass.UNKNOWN_OCCUPANCY.value, 1),
        )
    )
    assert ids == ("BUILD_ROAD", "CLASSIFIED_CLEAR", "CORNER_RAISE", "UNKNOWN_TILE")
    assert requirement_ids_for_counts(()) == ()


def test_blocked_offline_names_the_exact_blockers():
    blockers = blocked_offline()
    assert any("consumed" in blocker for blocker in blockers)
    assert any("RaiseTile/LowerTile" in blocker for blocker in blockers)
    assert any("house/station" in blocker or "schema-2" in blocker for blocker in blockers)


def test_fixed_demo_retained_evidence_still_assesses():
    if not FIXED_DEMO_RUN.exists():
        pytest.skip("optional retained fixed-demo native evidence is not installed")
    facts = retained_facts(FIXED_DEMO_RUN)
    pickups, deliveries = _seed17_stops(facts)
    diagnosis = assess_world_feasibility(facts, pickups[:4], deliveries[:4])
    assert diagnosis.observed_tiles == facts.region.width * facts.region.height
    # A CLEAR overlay cannot regress an already-supported assessment below the
    # supported tier: supported sections stay reported under supported codes.
    classes = {t.tile_id: TileClass.CLEAR.value for t in facts.tiles}
    favorable = assess_world_feasibility(facts, pickups[:4], deliveries[:4], tile_classes=classes)
    rank = {
        code: index
        for index, code in enumerate(
            (
                FeasibilityCode.NO_CONNECTED_CORRIDOR,
                FeasibilityCode.UNSUPPORTED_CONSTRUCTION,
                FeasibilityCode.INCOMPLETE_TILE_CLASSIFICATION,
                FeasibilityCode.TERRAIN_MODIFICATION_REQUIRED,
                FeasibilityCode.CONNECTED_WITHOUT_MODIFICATION,
                FeasibilityCode.SEARCH_BUDGET_EXCEEDED,
            )
        )
    }
    assert rank[favorable.code] >= min(
        rank[diagnosis.code], rank[FeasibilityCode.TERRAIN_MODIFICATION_REQUIRED]
    )


def test_tile_classes_helper_maps_index_to_classification_dict():
    region = Region(x=0, y=0, width=1, height=1)
    request = TileClassificationRequest("idx-1", region, 0)
    response = TileClassificationResponse(
        request.request_id,
        region,
        0,
        2,
        64,
        64,
        712282,
        712282,
        ((0, 1, 0, 1 << 13, None, -1),),  # house bit per CLASSIFICATION_FLAG_NAMES
        None,
        False,
    )
    index = TileClassificationIndex.from_pages(request, (response,))
    assert tile_classes(index) == {0: TileClass.HOUSE}
    assert classify_segment.__module__ == "app.planning.p08_terrain"
