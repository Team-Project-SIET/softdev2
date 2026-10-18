"""Reassessment workflow over a schema-2 classification census (Tasks C+D).

Offline only: no OpenTTD launch, no AdminPort connection, no authorization
consumption. The Seed 17 census replay below synthesizes classification pages
EXACTLY from the retained TileFact projection (including leaving the 19
projection-dropped tiles without any predicate, i.e. UNKNOWN); it demonstrates
the binding workflow and remains reproducible from retained evidence alone.
Nothing here claims a native measurement: a real census still requires the
separately prepared capture (see proof/terrain_classification_preparation.py).
"""

import hashlib
import json

import pytest
from test_p08_bounded_terrain import SEED17_RUN, retained_facts
from test_p08_feasibility_classification import _seed17_stops
from test_tile_classification_receipt import (
    exchanges_for,
)

from app.planning.construction_readiness import (
    BUILD_ROAD,
    CLASSIFIED_CLEAR,
    CLASSIFIED_OBSTACLE_REQUIREMENTS,
    CORNER_RAISE,
    NATIVE_SUPPORT_NOT_IMPLEMENTED,
    OCCUPANCY_CONVERSION,
    UNKNOWN_TILE,
    classification_readiness_report,
    readiness_summary,
    requirement_for_tile_class,
)
from app.planning.p08_terrain import FeasibilityCode, assess_world_feasibility
from app.simulation.openttd.tile_classification import (
    CLASSIFICATION_SCHEMA_VERSION,
    TileClass,
    TileClassificationSweep,
    classification_plan,
)


def retained_welcome():
    value = json.loads((SEED17_RUN / "runtime-identity.json").read_bytes())
    return value["welcome"]


def replay_census_request_id():
    return "seed17-tile-classification-v2"


def offline_retained_digest():
    """Provenance digest for the replay: the retained observation file."""
    return hashlib.sha256((SEED17_RUN / "network-facts-0.json").read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def retained_facts_value():
    if not (SEED17_RUN / "network-facts-0.json").is_file():
        pytest.skip("retained Seed 17 native evidence is not installed")
    facts = retained_facts(SEED17_RUN)
    assert (facts.region.width, facts.region.height) == (15, 30)
    assert len(facts.tiles) == 450
    return facts


@pytest.fixture(scope="module")
def replay_sweep(retained_facts_value):
    """A bound synthetic census replaying the retained TileFact projection."""
    facts = retained_facts_value
    welcome = retained_welcome()
    requests, exchanges = exchanges_for(
        facts,
        facts.source.map_width,
        facts.source.map_height,
        request_id=replay_census_request_id(),
    )
    return TileClassificationSweep.record(
        requests,
        exchanges,
        retained_facts=facts,
        retained_facts_digest=offline_retained_digest(),
        retained_welcome=welcome,
        observed_welcome=dict(welcome),
    )


def test_task_d_maps_every_classified_obstacle_to_its_requirement():
    for tile_class in (
        TileClass.HOUSE,
        TileClass.STATION,
        TileClass.INDUSTRY,
        TileClass.WATER,
        TileClass.COAST,
        TileClass.AIRPORT,
        TileClass.ROAD,
        TileClass.RAIL,
        TileClass.DOCK,
    ):
        assert requirement_for_tile_class(tile_class.value) == OCCUPANCY_CONVERSION.requirement_id
    for tile_class in (
        TileClass.TREES,
        TileClass.FARM,
        TileClass.ROCK,
        TileClass.ROUGH,
    ):
        assert requirement_for_tile_class(tile_class.value) == CLASSIFIED_CLEAR.requirement_id
    assert requirement_for_tile_class("CLEAR", slope=0) == BUILD_ROAD.requirement_id
    assert requirement_for_tile_class("CLEAR", slope=0x8) == CORNER_RAISE.requirement_id
    assert (
        requirement_for_tile_class(TileClass.UNKNOWN_OCCUPANCY.value) == UNKNOWN_TILE.requirement_id
    )
    with pytest.raises(ValueError):
        requirement_for_tile_class("INVENTED")
    assert set(CLASSIFIED_OBSTACLE_REQUIREMENTS) == {
        value.value for value in TileClass if value not in (TileClass.CLEAR,)
    }


def test_task_d_report_distinguishes_planning_from_native_support():
    report = classification_readiness_report({value.value: 1 for value in TileClass})
    by_requirement = {entry["requirement_id"] for entry in report}
    assert {
        BUILD_ROAD.requirement_id,
        CLASSIFIED_CLEAR.requirement_id,
        CORNER_RAISE.requirement_id,
        OCCUPANCY_CONVERSION.requirement_id,
        UNKNOWN_TILE.requirement_id,
    } <= by_requirement
    ids = {entry["requirement_id"]: entry for entry in report}
    assert ids[BUILD_ROAD.requirement_id]["native_support"] == "NATIVELY_EXECUTED_IN_FIXED_PATH"
    assert ids[CLASSIFIED_CLEAR.requirement_id]["planning_only"] is False
    # Raising/lowering corners is planning support only: no staged package
    # issues the native command yet.
    assert ids[CORNER_RAISE.requirement_id]["native_support"] == "NOT_IMPLEMENTED"
    assert ids[CORNER_RAISE.requirement_id]["planning_only"] is True
    assert ids[OCCUPANCY_CONVERSION.requirement_id]["native_support"] == "OUT_OF_SCOPE"
    assert ids[UNKNOWN_TILE.requirement_id]["native_support"] == NATIVE_SUPPORT_NOT_IMPLEMENTED
    assert ids[UNKNOWN_TILE.requirement_id]["native_api"] == "none (classification unavailable)"
    summary = readiness_summary(UNKNOWN_TILE.requirement_id)
    assert "schema-2" in summary.missing_implementation


def test_retained_replay_binds_the_full_census(replay_sweep):
    sweep = replay_sweep
    assert CLASSIFICATION_SCHEMA_VERSION == 2
    assert sweep.bound is True
    assert sweep.pages == 90
    assert len(sweep.facts) == 450
    assert sweep.region.x == 170 and sweep.region.y == 171
    assert len(sweep.receipts) == 90
    assert sweep.class_counts  # non-empty distribution
    assert all(count > 0 for count in sweep.class_counts.values())
    summary = json.loads(sweep.completeness_summary())
    assert summary["bound"] is True and summary["pages"] == 90
    assert summary["region"] == [170, 171, 15, 30]


def test_retained_replay_reproduces_the_retained_assessment(retained_facts_value, replay_sweep):
    """A census replaying exactly the retained projection changes nothing.

    The retained assessment (legacy projection only) and the fused assessment
    (same tiles replayed through the schema-2 wire) must produce the identical
    corridor and code: the replay adds no information, only representation.
    """
    facts = retained_facts_value
    pickups, deliveries = _seed17_stops(facts)
    legacy = assess_world_feasibility(facts, pickups, deliveries)
    classes, flags = replay_sweep.require_bound()
    merged = assess_world_feasibility(
        facts, pickups, deliveries, tile_classes=classes, tile_flags=flags
    )
    assert legacy.code == FeasibilityCode.INCOMPLETE_TILE_CLASSIFICATION
    assert merged.code == legacy.code
    assert merged.corridor == legacy.corridor
    assert merged.segment_counts == legacy.segment_counts
    assert merged.digest == legacy.digest
    assert merged.observed_tiles == 450
    # The 19 projection-dropped tiles stay UNKNOWN in both runs.
    from_count = dict(merged.segment_counts)
    unknown = from_count["UNKNOWN_OCCUPANCY"]
    assert unknown == 19
    # Machine-readable feasibility output for the operational summary.
    payload = json.dumps(merged.as_dict(), sort_keys=True)
    assert json.loads(payload)["code"] == FeasibilityCode.INCOMPLETE_TILE_CLASSIFICATION


def test_replay_request_plan_is_bounded_and_pinned(retained_facts_value):
    facts = retained_facts_value
    plan = classification_plan(facts.region, replay_census_request_id())
    bodies = [request.to_bytes().decode() for request in plan]
    assert all('"schema":2' in body for body in bodies)
    assert all(replay_census_request_id() in body for body in bodies)
    assert bodies[0].startswith("[170,171,") or '"region":[170,171,' in bodies[0]
    assert all(len(payload) <= 159 for payload in [request.to_bytes() for request in plan])
    assert len(bodies) == 90 and len(set(bodies)) == 90


def test_unknown_tile_ids_never_fabricated_into_the_replay(retained_facts_value, replay_sweep):
    """The replay must not classify any tile the retained record leaves open."""
    facts = retained_facts_value
    dropped = {
        t.tile_id
        for t in facts.tiles
        if not t.buildable
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
                t.industry_id is not None,
            )
        )
    }
    assert len(dropped) == 19
    classes = dict(replay_sweep.tile_classes)
    for tile_id in dropped:
        assert classes[tile_id] is TileClass.UNKNOWN_OCCUPANCY


def test_offline_preparation_stays_separate_from_the_replay(retained_facts_value):
    """The replay is not a native claim: the prepared capture stays PENDING."""
    from app.simulation.openttd.proof import terrain_classification_preparation as prep

    seams = prep.validate_staging_seams()
    assert seams["classification_package_digest"]
    assert prep.retained_facts().region == retained_facts_value.region
    plan = prep.request_plan()
    assert len(plan) == 90
    assert len({payload.decode() for payload in plan}) == 90
    argv = prep.launch_command_template("staged/openttd.cfg")["argv"]
    assert "-G" in argv and "17" in argv
    assert "-D127.0.0.1:{reserved_game_port}" in argv
