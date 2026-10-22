"""P08 public preparation seams, using synthetic worlds only."""

import json
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.planning.preparation.canonical import authoritative_snapshot, snapshot_hash
from app.planning.preparation.domain import (
    ExtractedCargo,
    ExtractedIndustry,
    ExtractedRoadEngine,
    ExtractedTile,
    ExtractedWorldSnapshot,
    IndustryCargoFact,
    PreparationRequest,
    SupportedWorldProfile,
    TileCargoFact,
)


def synthetic_world():
    tiles = []
    for y in range(8):
        for x in range(12):
            index = y * 12 + x
            industry_id = 1 if (x, y) == (1, 3) else 2 if (x, y) == (10, 3) else None
            cargo = ()
            if max(abs(x - 1), abs(y - 3)) <= 3:
                cargo = (TileCargoFact(cargo_id=0, production=1, acceptance_eighths=0),)
            if max(abs(x - 10), abs(y - 3)) <= 3:
                cargo = (TileCargoFact(cargo_id=0, production=0, acceptance_eighths=8),)
            tiles.append(
                ExtractedTile(
                    tile_index=index,
                    x=x,
                    y=y,
                    height=1,
                    slope=0,
                    land_class="land",
                    occupancy="industry" if industry_id else "vacant",
                    transport_occupied=False,
                    industry_id=industry_id,
                    build_eligible=industry_id is None,
                    clearing_required=False,
                    cargo_facts=cargo,
                )
            )
    return ExtractedWorldSnapshot(
        schema_version=1,
        profile=SupportedWorldProfile(),
        width_tiles=12,
        height_tiles=8,
        seed=42,
        preparation_date=date(1950, 1, 1),
        company_id=0,
        source_save_digest="a" * 64,
        prepared_save_digest="a" * 64,
        policy_version="p08-v1",
        complete=True,
        tiles=tuple(tiles),
        industries=(
            ExtractedIndustry(
                industry_id=1,
                name="Mine",
                anchor_tile=37,
                footprint=(37,),
                cargos=(IndustryCargoFact(cargo_id=0, last_month_production=40, accepts=False),),
            ),
            ExtractedIndustry(
                industry_id=2,
                name="Power station",
                anchor_tile=46,
                footprint=(46,),
                cargos=(IndustryCargoFact(cargo_id=0, last_month_production=0, accepts=True),),
            ),
        ),
        cargos=(ExtractedCargo(cargo_id=0, label="COAL", name="Coal", freight=True),),
        engines=(
            ExtractedRoadEngine(
                engine_id=7,
                name="Coal truck",
                default_cargo_id=0,
                freight=True,
                road_type=0,
                depot_class="road",
                immediately_buildable=True,
                articulated=False,
                refit_required=False,
                default_capacity=20,
                purchase_cost_gbp=Decimal("100"),
                running_cost_gbp_per_year=Decimal("365"),
                native_speed_units=40,
            ),
        ),
        road_build_cost_gbp=Decimal("2"),
        station_build_cost_gbp=Decimal("10"),
        depot_build_cost_gbp=Decimal("15"),
    )


def request():
    return PreparationRequest(
        scenario_id="synthetic", horizon_days=30, expected_source_save_digest="a" * 64
    )


def test_snapshot_enumeration_and_terrain_identity():
    world = synthetic_world()
    reversed_world = world.model_copy(
        update={
            "tiles": tuple(reversed(world.tiles)),
            "industries": tuple(reversed(world.industries)),
        }
    )
    assert snapshot_hash(world) == snapshot_hash(reversed_world)
    assert authoritative_snapshot(reversed_world).tiles[0].tile_index == 0
    changed = world.model_copy(
        update={"tiles": (world.tiles[0].model_copy(update={"height": 2}),) + world.tiles[1:]}
    )
    assert snapshot_hash(world) != snapshot_hash(changed)


def test_contracts_are_strict_immutable_and_forbid_unknowns():
    with pytest.raises(ValidationError):
        PreparationRequest.model_validate_json(
            json.dumps(
                {"scenario_id": "s", "horizon_days": "30", "expected_source_save_digest": "a" * 64}
            )
        )
    with pytest.raises(ValidationError):
        request().horizon_days = 2
    with pytest.raises(ValidationError):
        PreparationRequest.model_validate_json(
            json.dumps({**request().model_dump(mode="json"), "process_id": 1})
        )


def test_demand_deadline_quantity_and_deterministic_destination():
    from app.planning.preparation.candidates import select_demand

    world = synthetic_world()
    demand, count = select_demand(world, request())
    assert (demand.origin_id, demand.destination_id, demand.cargo_id, demand.quantity) == (
        1,
        2,
        0,
        40,
    )
    assert demand.latest_delivery_day == 29
    assert demand.earliest_day == 0
    assert count == 1
    extra = world.industries[1].model_copy(update={"industry_id": 3})
    world = world.model_copy(update={"industries": (extra,) + tuple(reversed(world.industries))})
    assert select_demand(world, request())[0].destination_id == 2


def test_zero_production_and_no_destination_are_typed():
    from app.planning.preparation.candidates import select_demand
    from app.planning.preparation.failures import PreparationError

    world = synthetic_world()
    for industries in ((world.industries[0],), (world.industries[1],)):
        with pytest.raises(PreparationError) as error:
            select_demand(world.model_copy(update={"industries": industries}), request())
        assert error.value.code == "NO_COMPATIBLE_DESTINATION"


def test_station_sampling_and_native_acceptance():
    from app.planning.preparation.candidates import station_candidates

    world = synthetic_world()
    pickup, pickup_report = station_candidates(world, request(), world.industries[0], 0, "pickup")
    delivery, report = station_candidates(world, request(), world.industries[1], 0, "delivery")
    assert len(pickup) == len(delivery) == 4
    assert pickup_report.eligible_count > 4
    assert report.eligible_count > 4
    assert len({s.tile_index for s in pickup}) == 4
    assert (
        pickup
        == station_candidates(
            world.model_copy(update={"tiles": tuple(reversed(world.tiles))}),
            request(),
            world.industries[0],
            0,
            "pickup",
        )[0]
    )
    rejected = tuple(
        t.model_copy(
            update={"cargo_facts": (TileCargoFact(cargo_id=0, production=0, acceptance_eighths=7),)}
        )
        for t in world.tiles
    )
    from app.planning.preparation.failures import PreparationError

    with pytest.raises(PreparationError, match="NO_STATION_CANDIDATE"):
        station_candidates(
            world.model_copy(update={"tiles": rejected}),
            request(),
            world.industries[1],
            0,
            "delivery",
        )


@pytest.mark.parametrize(
    "update",
    [
        {"slope": 1},
        {"land_class": "water"},
        {"occupancy": "other"},
        {"transport_occupied": True},
        {"clearing_required": True},
    ],
)
def test_unsupported_station_tiles_never_become_candidates(update):
    from app.planning.preparation.candidates import station_candidates
    from app.planning.preparation.failures import PreparationError

    world = synthetic_world()
    world = world.model_copy(
        update={"tiles": tuple(t.model_copy(update=update) for t in world.tiles)}
    )
    with pytest.raises(PreparationError, match="NO_STATION_CANDIDATE"):
        station_candidates(world, request(), world.industries[0], 0, "pickup")


def test_depot_is_deterministic_and_rejects_reserved_fronts():
    from app.planning.preparation.candidates import depot_candidate
    from app.planning.preparation.failures import PreparationError

    world = synthetic_world()
    depot = depot_candidate(world, frozenset())
    assert (depot.tile_index, depot.front_tile, depot.orientation) == (0, 1, "east")
    assert depot == depot_candidate(
        world.model_copy(update={"tiles": tuple(reversed(world.tiles))}), frozenset()
    )
    assert depot_candidate(world, frozenset({1})).front_tile != 1
    with pytest.raises(PreparationError, match="NO_DEPOT_CANDIDATE"):
        depot_candidate(world, frozenset(range(96)))


def test_corridor_anchor_orientation_and_ordered_alternatives():
    from app.planning.preparation.candidates import FacilitySite
    from app.planning.preparation.corridor import SearchBudget, search_corridors

    world = synthetic_world()
    a = FacilitySite(tile_index=26, front_tile=27, orientation="east")
    b = FacilitySite(tile_index=32, front_tile=31, orientation="west")
    paths = search_corridors(world, request(), a, b, 29, frozenset({26, 32}), SearchBudget())
    assert paths[0] == (26, 27, 28, 29, 30, 31, 32)
    assert len(paths) == 2
    for path in paths:
        assert 29 in path
        assert len(set(path)) == len(path)
        assert path[:2] == (26, 27)
        assert path[-2:] == (31, 32)
    assert paths == search_corridors(
        world, request(), a, b, 29, frozenset({26, 32}), SearchBudget()
    )


def test_corridor_obstacle_and_search_limit_are_distinct():
    from app.planning.preparation.candidates import FacilitySite
    from app.planning.preparation.corridor import SearchBudget, search_corridors
    from app.planning.preparation.domain import PreparationLimits
    from app.planning.preparation.failures import PreparationError

    world = synthetic_world()
    a = FacilitySite(tile_index=26, front_tile=27, orientation="east")
    b = FacilitySite(tile_index=32, front_tile=31, orientation="west")
    tiles = tuple(
        t.model_copy(update={"occupancy": "other"}) if t.tile_index == 28 else t
        for t in world.tiles
    )
    paths = search_corridors(
        world.model_copy(update={"tiles": tiles}),
        request(),
        a,
        b,
        29,
        frozenset({26, 32}),
        SearchBudget(),
    )
    assert 28 not in paths[0]
    limited = request().model_copy(update={"limits": PreparationLimits(search_states_per_pair=1)})
    with pytest.raises(PreparationError, match="CANDIDATE_LIMIT_EXCEEDED"):
        search_corridors(world, limited, a, b, 29, frozenset({26, 32}), SearchBudget())
    blocked = world.model_copy(
        update={
            "tiles": tuple(
                t.model_copy(update={"land_class": "water"}) if t.tile_index == 27 else t
                for t in world.tiles
            )
        }
    )
    with pytest.raises(PreparationError, match="UNSUPPORTED_TERRAIN"):
        search_corridors(blocked, request(), a, b, 29, frozenset({26, 32}), SearchBudget())


def test_preparation_projects_consumable_scenario_and_native_industry_identity():
    from app.planning.canonical import canonical_bytes, scenario_hash, world_manifest_hash
    from app.planning.execution import execution_payload
    from app.planning.optimizer import optimize_candidate_network
    from app.planning.preparation.projection import prepare_world
    from app.planning.runtime_world import runtime_projection_from_manifest
    from app.planning.validation import validate_execution_plan

    world = corridor_world()
    bundle = prepare_world(corridor_request(), world)
    assert len(bundle.scenario.cargo_demands) == 1
    assert bundle.scenario.cargo_demands[0].latest_delivery_day == 29
    assert bundle.scenario.world_fingerprint == world_manifest_hash(bundle.manifest)
    assert bundle.provenance.scenario_hash == scenario_hash(bundle.scenario)
    result = optimize_candidate_network(bundle.scenario)
    validate_execution_plan(result.plan, bundle.scenario)
    payload = execution_payload(result.plan, bundle.scenario, bundle.bindings)
    assert payload["actions"]
    assert runtime_projection_from_manifest(bundle.manifest)
    assert {s.world_id for s in bundle.manifest.resolved_sites if s.world_kind} == {1, 2}
    reverse = world.model_copy(
        update={
            "tiles": tuple(reversed(world.tiles)),
            "industries": tuple(reversed(world.industries)),
        }
    )
    assert canonical_bytes(bundle.scenario) == canonical_bytes(
        prepare_world(corridor_request(), reverse).scenario
    )


@pytest.mark.parametrize(
    "update",
    [
        {"articulated": True},
        {"default_cargo_id": 999},
        {"immediately_buildable": False},
        {"default_capacity": 0},
        {"refit_required": True},
    ],
)
def test_fleet_ineligible_engines_never_publish(update):
    from app.planning.preparation.failures import PreparationError
    from app.planning.preparation.projection import project_fleet

    world = synthetic_world()
    world = world.model_copy(update={"engines": (world.engines[0].model_copy(update=update),)})
    with pytest.raises(PreparationError, match="FLEET_CATALOG_UNAVAILABLE"):
        project_fleet(world, request(), 0)


def corridor_world():
    world = synthetic_world()
    return world.model_copy(
        update={
            "tiles": tuple(
                t.model_copy(update={"build_eligible": False, "occupancy": "other"})
                if t.industry_id is None
                and not (t.y == 3 and 2 <= t.x <= 9)
                and (t.x, t.y) != (5, 4)
                else t
                for t in world.tiles
            )
        }
    )


def corridor_request():
    from app.planning.preparation.domain import PreparationLimits

    return request().model_copy(update={"limits": PreparationLimits(stations_per_role=1)})


@pytest.mark.parametrize(
    "field", ["map_tiles", "industries", "infrastructure_candidates", "scenario_bytes"]
)
def test_preparation_hard_bounds_never_publish_partial_scenario(field):
    from app.planning.preparation.domain import PreparationLimits
    from app.planning.preparation.failures import PreparationError
    from app.planning.preparation.projection import prepare_world

    req = corridor_request().model_copy(
        update={"limits": PreparationLimits.model_validate({"stations_per_role": 1, field: 1})}
    )
    with pytest.raises(PreparationError, match="CANDIDATE_LIMIT_EXCEEDED"):
        prepare_world(req, corridor_world())


@pytest.mark.parametrize(
    "field", ["corridor_length", "search_states_per_pair", "aggregate_expansions"]
)
def test_search_bounds_are_never_reported_as_infeasible(field):
    from app.planning.preparation.candidates import FacilitySite
    from app.planning.preparation.corridor import SearchBudget, search_corridors
    from app.planning.preparation.domain import PreparationLimits
    from app.planning.preparation.failures import PreparationError

    req = corridor_request().model_copy(
        update={"limits": PreparationLimits.model_validate({"stations_per_role": 1, field: 2})}
    )
    with pytest.raises(PreparationError, match="CANDIDATE_LIMIT_EXCEEDED"):
        search_corridors(
            corridor_world(),
            req,
            FacilitySite(tile_index=38, front_tile=39, orientation="east"),
            FacilitySite(tile_index=45, front_tile=44, orientation="west"),
            41,
            frozenset({38, 45, 53}),
            SearchBudget(),
        )


def test_relationship_and_fleet_overflow_are_not_silently_clipped():
    from app.planning.preparation.candidates import select_demand
    from app.planning.preparation.domain import PreparationLimits
    from app.planning.preparation.failures import PreparationError
    from app.planning.preparation.projection import project_fleet

    world = synthetic_world()
    extra = world.industries[1].model_copy(update={"industry_id": 3})
    req = request().model_copy(
        update={"limits": PreparationLimits(relationships=1, fleet_options=1)}
    )
    with pytest.raises(PreparationError, match="CANDIDATE_LIMIT_EXCEEDED"):
        select_demand(world.model_copy(update={"industries": world.industries + (extra,)}), req)
    engine = world.engines[0].model_copy(update={"engine_id": 8})
    with pytest.raises(PreparationError, match="CANDIDATE_LIMIT_EXCEEDED"):
        project_fleet(world.model_copy(update={"engines": world.engines + (engine,)}), req, 0)


@pytest.mark.parametrize(
    "profile",
    [
        {"openttd_version": "14.0"},
        {"base_set_name": "other"},
        {"landscape": "arctic"},
        {"newgrfs": ("mod",)},
        {"competing_active_companies": 1},
        {"preparation_compatible": False},
        {"road_type": 1},
        {"catchment_radius": 4},
    ],
)
def test_unsupported_world_is_explicit(profile):
    from app.planning.preparation.failures import PreparationError
    from app.planning.preparation.projection import prepare_world

    world = synthetic_world()
    with pytest.raises(PreparationError, match="UNSUPPORTED_WORLD"):
        prepare_world(
            request(),
            world.model_copy(update={"profile": world.profile.model_copy(update=profile)}),
        )


@pytest.mark.parametrize(
    "change,code",
    [
        ("save", "WORLD_CHANGED_DURING_PREPARATION"),
        ("missing", "EXTRACTION_INCOMPLETE"),
        ("incomplete", "EXTRACTION_INCOMPLETE"),
        ("cargo", "UNKNOWN_CARGO"),
        ("duplicate", "CATALOG_IDENTITY_MISMATCH"),
    ],
)
def test_invalid_extraction_is_never_projected(change, code):
    from app.planning.preparation.failures import PreparationError
    from app.planning.preparation.projection import prepare_world

    world = synthetic_world()
    updates = {
        "save": {"source_save_digest": "b" * 64},
        "missing": {"tiles": world.tiles[:-1]},
        "incomplete": {"complete": False},
        "cargo": {"cargos": (world.cargos[0].model_copy(update={"label": "MOD"}),)},
        "duplicate": {"engines": world.engines + world.engines},
    }
    with pytest.raises(PreparationError, match=code):
        prepare_world(request(), world.model_copy(update=updates[change]))


def test_all_selectable_combinations_and_disconnected_depot_rejection():
    from app.planning.canonical import world_manifest_hash
    from app.planning.execution import execution_payload
    from app.planning.preparation.failures import PreparationError
    from app.planning.preparation.projection import prepare_world
    from app.planning.preparation.safety import check_combination_safety, combination_witnesses

    world = corridor_world()
    # Multiple fleet alternatives prove the P05 cross-product, not just the winner.
    world = world.model_copy(
        update={"engines": world.engines + (world.engines[0].model_copy(update={"engine_id": 8}),)}
    )
    bundle = prepare_world(corridor_request(), world)
    witnesses = tuple(combination_witnesses(bundle.scenario))
    assert len(witnesses) == 2
    for witness in witnesses:
        execution_payload(witness, bundle.scenario, bundle.bindings)
    # Change only depot orientation, keep P02 manifest equality so P06 connectivity is exercised.
    locations = tuple(
        s.model_copy(update={"orientation": "south"}) if s.location_id == "shared-depot" else s
        for s in bundle.scenario.locations
    )
    sites = tuple(
        s.model_copy(update={"orientation": "south"}) if s.location_id == "shared-depot" else s
        for s in bundle.manifest.resolved_sites
    )
    manifest = bundle.manifest.model_copy(update={"resolved_sites": sites})
    fingerprint = world_manifest_hash(manifest)
    locations = tuple(
        s.model_copy(
            update={
                "world_reference": s.world_reference.model_copy(
                    update={"world_fingerprint": fingerprint}
                )
            }
        )
        if s.world_reference
        else s
        for s in locations
    )
    candidates = tuple(
        c.model_copy(update={"orientation": "south"}) if c.site_id == "shared-depot" else c
        for c in bundle.scenario.infrastructure_candidates
    )
    scenario = bundle.scenario.model_copy(
        update={
            "locations": locations,
            "world_manifest": manifest,
            "world_fingerprint": fingerprint,
            "infrastructure_candidates": candidates,
        }
    )
    with pytest.raises(PreparationError, match="INVALID_PREPARATION_OUTPUT"):
        check_combination_safety(scenario, bundle.bindings, world)


def test_corridor_tile_order_is_semantic_and_save_digest_changes_world_identity():
    from app.planning.canonical import canonical_bytes, world_manifest_hash
    from app.planning.domain import ConstructionKind
    from app.planning.preparation.projection import prepare_world

    bundle = prepare_world(corridor_request(), corridor_world())
    segment = next(
        c for c in bundle.scenario.infrastructure_candidates if c.kind is ConstructionKind.SEGMENT
    )
    assert canonical_bytes(segment) != canonical_bytes(
        segment.model_copy(update={"tiles": tuple(reversed(segment.tiles))})
    )
    assert world_manifest_hash(bundle.manifest) != world_manifest_hash(
        bundle.manifest.model_copy(update={"source_digest": "b" * 64})
    )


def test_p05_cost_preconditions_are_checked_before_publication():
    from app.planning.preparation.failures import PreparationError
    from app.planning.preparation.projection import prepare_world

    world = corridor_world()
    huge = world.engines[0].model_copy(update={"purchase_cost_gbp": Decimal("1e40")})
    with pytest.raises(PreparationError, match="INVALID_PREPARATION_OUTPUT"):
        prepare_world(corridor_request(), world.model_copy(update={"engines": (huge,)}))


def test_fleet_native_capacity_mismatch_is_rejected_by_combination_checker():
    from app.planning.preparation.failures import PreparationError
    from app.planning.preparation.projection import prepare_world
    from app.planning.preparation.safety import check_combination_safety

    world = corridor_world()
    bundle = prepare_world(corridor_request(), world)
    option = bundle.scenario.fleet_options[0]
    from app.planning.domain import RoadFleetOption

    assert isinstance(option, RoadFleetOption)
    changed = option.model_copy(
        update={"vehicle": option.vehicle.model_copy(update={"capacity_cargo_units": 19})}
    )
    scenario = bundle.scenario.model_copy(update={"fleet_options": (changed,)})
    with pytest.raises(PreparationError, match="INVALID_PREPARATION_OUTPUT"):
        check_combination_safety(scenario, bundle.bindings, world)


def test_p08_plan_executes_in_existing_p06_squirrel_controlled_executor():
    from app.planning.execution_evidence import parse_execution_evidence
    from app.planning.optimizer import optimize_candidate_network
    from app.planning.preparation.projection import prepare_world
    from tests.test_planning_execution import run_executor

    world = synthetic_world()
    tiles = []
    for y in range(64):
        for x in range(64):
            index = y * 64 + x
            industry = 1 if (x, y) == (4, 4) else 2 if (x, y) == (20, 4) else None
            buildable = (y == 4 and 5 <= x <= 19) or (x, y) == (6, 5)
            facts = ()
            if max(abs(x - 4), abs(y - 4)) <= 3:
                facts = (TileCargoFact(cargo_id=0, production=1, acceptance_eighths=0),)
            if max(abs(x - 20), abs(y - 4)) <= 3:
                facts = (TileCargoFact(cargo_id=0, production=0, acceptance_eighths=8),)
            tiles.append(
                ExtractedTile(
                    tile_index=index,
                    x=x,
                    y=y,
                    height=1,
                    slope=0,
                    land_class="land",
                    occupancy="industry" if industry else "vacant" if buildable else "other",
                    transport_occupied=False,
                    industry_id=industry,
                    build_eligible=buildable,
                    clearing_required=False,
                    cargo_facts=facts,
                )
            )
    world = world.model_copy(
        update={
            "tiles": tuple(tiles),
            "width_tiles": 64,
            "height_tiles": 64,
            "seed": 17,
            "industries": tuple(
                i.model_copy(
                    update={
                        "anchor_tile": 260 if i.industry_id == 1 else 276,
                        "footprint": (260 if i.industry_id == 1 else 276,),
                    }
                )
                for i in world.industries
            ),
            "engines": (world.engines[0].model_copy(update={"engine_id": 10, "name": "lorry"}),),
        }
    )
    bundle = prepare_world(corridor_request(), world)
    plan = optimize_candidate_network(bundle.scenario).plan
    log, calls = run_executor(plan, bundle.scenario, bundle.bindings)
    receipt = parse_execution_evidence(log, plan, bundle.scenario, bundle.bindings)
    assert receipt.result == "success"
    assert any(c.startswith("road_segment") for c in calls)


def test_native_speed_uses_documented_13_4_fixed_point_conversion():
    from app.planning.preparation.projection import project_fleet

    options, _ = project_fleet(synthetic_world(), request(), 0)
    assert options[0].vehicle.speed_km_per_hour == Decimal("40.2336")


@pytest.mark.parametrize(
    "kind", ["demands", "depots", "stations", "corridors", "fleet", "total", "length"]
)
def test_output_count_bounds_are_typed_even_for_invalid_advertised_spaces(kind):
    from app.planning.domain import ConstructionKind
    from app.planning.preparation.failures import PreparationError
    from app.planning.preparation.projection import prepare_world, validate_candidate_limits

    bundle = prepare_world(corridor_request(), corridor_world())
    scenario = bundle.scenario
    candidates = scenario.infrastructure_candidates
    segment = next(c for c in candidates if c.kind is ConstructionKind.SEGMENT)
    depot = next(c for c in candidates if c.kind is ConstructionKind.DEPOT)
    station = next(c for c in candidates if c.kind is ConstructionKind.STATION)
    updates = {
        "demands": {"cargo_demands": scenario.cargo_demands * 2},
        "depots": {"infrastructure_candidates": candidates + (depot,)},
        "stations": {"infrastructure_candidates": candidates + (station,)},
        "corridors": {"infrastructure_candidates": candidates + (segment, segment)},
        "fleet": {"fleet_options": scenario.fleet_options * 33},
        "total": {"infrastructure_candidates": candidates * 13},
        "length": {
            "infrastructure_candidates": candidates
            + (segment.model_copy(update={"tiles": segment.tiles * 600}),)
        },
    }
    with pytest.raises(PreparationError, match="CANDIDATE_LIMIT_EXCEEDED"):
        validate_candidate_limits(
            scenario.model_copy(update=updates[kind]), corridor_request(), bundle.snapshot
        )


def test_supported_search_exhaustion_is_infeasible_not_a_limit():
    from app.planning.preparation.candidates import FacilitySite
    from app.planning.preparation.corridor import SearchBudget, search_corridors
    from app.planning.preparation.failures import PreparationError

    world = corridor_world()
    world = world.model_copy(
        update={
            "tiles": tuple(
                t.model_copy(update={"occupancy": "other"}) if t.tile_index == 41 else t
                for t in world.tiles
            )
        }
    )
    with pytest.raises(PreparationError, match="NO_FEASIBLE_CORRIDOR"):
        search_corridors(
            world,
            corridor_request(),
            FacilitySite(tile_index=38, front_tile=39, orientation="east"),
            FacilitySite(tile_index=45, front_tile=44, orientation="west"),
            39,
            frozenset({38, 45, 53}),
            SearchBudget(),
        )
