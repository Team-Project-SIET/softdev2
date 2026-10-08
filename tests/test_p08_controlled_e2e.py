"""Owned controlled artifacts -> existing WPO/P08/P05, with independent oracles.

No native issuer: the accepted recipe drives the existing in-memory qualification
fixture. All subsequent artifacts use the public owned-byte admission functions.
"""

import asyncio
import hashlib
import json
import socket
import subprocess
from copy import copy
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from pathlib import Path
from unittest.mock import patch

import pytest
from test_qualification_coordinator import QualificationWire, collect
from test_supplemental_planning_contracts import correspondence, fact_dict

from app.planning.canonical import canonical_bytes, plan_hash, scenario_hash, world_manifest_hash
from app.planning.domain import (
    ConstructionKind,
    Contract,
    PlanningScenario,
    PreparedWorldManifest,
    RoadFleetOption,
)
from app.planning.optimizer import (
    OptimizerFailure,
    OptimizerFailureCode,
    _cost_units,
    optimize_candidate_network,
)
from app.planning.p08_adapter import (
    MAX_PATH_EXPANSIONS,
    MAX_STATION_PAIRS,
    MAX_STATIONS_PER_ROLE,
    MAX_VEHICLES,
    MonthlyBatchPolicy,
    RoadOutcome,
    adapt_planning_facts,
)
from app.planning.p08_road import ControlledRoadScenario, NoRoadScenario, generate_road_scenario
from app.planning.validation import PlanningValidationError, validate_execution_plan
from app.simulation.openttd.cargo_page import CargoCatalogRecord
from app.simulation.openttd.industry_cargo import IndustryCargoCapability
from app.simulation.openttd.observation_protocol import BridgeProtocolError
from app.simulation.openttd.planning_fact_artifacts import (
    MAX_ARTIFACT_BYTES,
    import_planning_facts,
    import_prepared_source,
)
from app.simulation.openttd.planning_fact_input import ValidatedPlanningFactInput
from app.simulation.openttd.prepared_source_correspondence import ControlledSourceLinks, SourceTrust
from app.simulation.openttd.production_observation import IndustryProductionObservation
from app.simulation.openttd.supplemental_planning_facts import (
    MAX_COVERAGE,
    MAX_ENGINES,
    MAX_TILES,
    CargoID,
    IndustryID,
    PlanningFactError,
    SupplementalPlanningFacts,
    UInt,
)
from app.simulation.openttd.world_planning_observation import WorldPlanningObservation

FIXTURES = Path(__file__).parent / "fixtures/p08_controlled_e2e"


class ControlledRecipe(Contract):
    """Test-only fixture parameters; never a persisted WPO/native proof schema."""

    producer_id: IndustryID
    acceptor_id: IndustryID
    cargo_id: CargoID
    other_cargo_id: CargoID
    quantity: UInt
    empty_targets: bool = False


RECIPE = ControlledRecipe(
    producer_id=11, acceptor_id=16, cargo_id=3, other_cargo_id=9, quantity=120
)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def qualified_fixture(recipe: ControlledRecipe) -> WorldPlanningObservation:
    """Use existing complete qualification/evidence validators on a fake stream."""

    async def run():
        wire = QualificationWire(
            industries=()
            if recipe.empty_targets
            else tuple(sorted((recipe.producer_id, recipe.acceptor_id))),
            produces=() if recipe.empty_targets else (recipe.cargo_id,),
        )
        wire.cargoes = tuple(sorted((recipe.cargo_id, recipe.other_cargo_id)))
        wire.metrics = (recipe.quantity, 0, 0)
        result = await collect(wire, await wire.owner())
        return WorldPlanningObservation(result.verification.stability.final, result)

    def capability(i, produces, accepts):
        return IndustryCargoCapability(
            i,
            (recipe.cargo_id,) if i == recipe.producer_id else (),
            (recipe.cargo_id,) if i == recipe.acceptor_id else (),
        )

    def catalog(i, label, freight, effect, classes):
        return CargoCatalogRecord(
            i, "434F414C" if i == recipe.cargo_id else "474F4F44", freight, effect, classes
        )

    with (
        patch("test_structural_world.IndustryCargoCapability", side_effect=capability),
        patch("test_structural_world.CargoCatalogRecord", side_effect=catalog),
    ):
        return asyncio.run(run())


def region_bundle(world, recipe=RECIPE, width=8, height=4):
    d = fact_dict(world)
    x0 = min(recipe.producer_id, recipe.acceptor_id) - 1
    map_width = world.context.world.map_width
    d["region"] = dict(x=x0, y=0, width=width, height=height)
    prototype = d["tiles"][0]
    d["tiles"] = [
        dict(
            prototype,
            tile_id=y * map_width + x,
            x=x,
            y=y,
            industry_id=x
            if y == 1 and x in (recipe.producer_id, recipe.acceptor_id) and not recipe.empty_targets
            else None,
            buildable=not (
                y == 1
                and x in (recipe.producer_id, recipe.acceptor_id)
                and not recipe.empty_targets
            ),
        )
        for y in range(height)
        for x in range(x0, x0 + width)
    ]
    d["coverage_scopes"] = (
        []
        if recipe.empty_targets
        else [
            dict(industry_id=recipe.producer_id, cargo_id=recipe.cargo_id, role="pickup"),
            dict(industry_id=recipe.acceptor_id, cargo_id=recipe.cargo_id, role="delivery"),
        ]
    )
    d["coverage"] = []
    for t in d["tiles"]:
        for scope in d["coverage_scopes"]:
            covered = t["x"] == scope["industry_id"] and t["y"] == 2
            d["coverage"].append(
                dict(
                    tile_id=t["tile_id"],
                    **scope,
                    producer_count=int(covered and scope["role"] == "pickup"),
                    acceptance_eighths=8 if covered and scope["role"] == "delivery" else 0,
                    industry_covered=covered,
                )
            )
    d["engines"][0].update(
        default_cargo_id=recipe.cargo_id,
        engine_id=23,
        capacity_cargo_units=30,
        purchase_cost_gbp=1000,
        running_cost_gbp_per_economy_year=366,
    )
    return d


def write_bundle(root, world, d):
    f = SupplementalPlanningFacts.model_validate_json(json_bytes(d))
    raw = json_bytes(
        dict(
            schema_version=1,
            source_class="CONTROLLED_FIXTURE",
            facts_digest=f.semantic_digest,
            facts=f.model_dump(mode="json"),
        )
    )
    (root / "supplemental.json").write_bytes(raw)
    return digest(raw)


def materialize(root, recipe=RECIPE):
    """Generate new test artifacts only; never changes retained fixture inputs."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "recipe.json").write_bytes(canonical_bytes(recipe) + b"\n")
    world = qualified_fixture(recipe)
    c = correspondence(world)
    (root / "original-source.bin").write_bytes(b"original save fixture")
    (root / "manifest.json").write_bytes(canonical_bytes(c.manifest) + b"\n")
    (root / "correspondence.json").write_bytes(canonical_bytes(c.links) + b"\n")
    write_bundle(root, world, region_bundle(world, recipe))
    names = (
        "recipe.json",
        "original-source.bin",
        "manifest.json",
        "correspondence.json",
        "supplemental.json",
    )
    accepted = {name: digest((root / name).read_bytes()) for name in names}
    (root / "accepted-digests.json").write_bytes(json_bytes(accepted))
    return world


def accepted_bytes(root, name, accepted):
    raw = (root / name).read_bytes()
    if len(raw) > MAX_ARTIFACT_BYTES or digest(raw) != accepted[name]:
        raise PlanningFactError("controlled accepted bytes mismatch")
    return raw


def admit(root, policy=None, world=None):
    """Direct test composition of actual public entry points, not a coordinator."""
    accepted = json.loads((root / "accepted-digests.json").read_bytes())
    recipe = ControlledRecipe.model_validate_json(accepted_bytes(root, "recipe.json", accepted))
    world = qualified_fixture(recipe) if world is None else world
    imported = import_planning_facts(
        root, "supplemental.json", expected_bytes_digest=accepted["supplemental.json"], world=world
    )
    manifest = PreparedWorldManifest.model_validate_json(
        accepted_bytes(root, "manifest.json", accepted)
    )
    links = ControlledSourceLinks.model_validate_json(
        accepted_bytes(root, "correspondence.json", accepted)
    )
    prepared = import_prepared_source(
        root, "original-source.bin", world=world, manifest=manifest, links=links
    )
    value = ValidatedPlanningFactInput(world, imported.artifact.facts, prepared.correspondence)
    road = generate_road_scenario(
        adapt_planning_facts(value, policy or MonthlyBatchPolicy(start_date=date(2001, 1, 1)))
    )
    assert imported.trust == prepared.correspondence.trust == SourceTrust.CONTROLLED_FIXTURE
    assert prepared.trust == SourceTrust.SOURCE_BYTES_VERIFIED  # byte fact, not runtime trust
    return imported, prepared, road


@pytest.fixture
def owned(tmp_path):
    # Copy complete accepted inputs before test execution; no accepted fixture mutation.
    for path in FIXTURES.iterdir():
        if path.is_file():
            (tmp_path / path.name).write_bytes(path.read_bytes())
    return tmp_path


def revise_bundle(root, change, world=None):
    _, _, road = admit(root, world=world)
    data = road.input.facts.model_dump(mode="json")
    change(data)
    # Negative admission cases can deliberately contain invalid schema/semantics.
    old = json.loads((root / "supplemental.json").read_bytes())
    try:
        old["facts_digest"] = SupplementalPlanningFacts.model_validate_json(
            json_bytes(data)
        ).semantic_digest
    except ValueError:
        pass
    old["facts"] = data
    raw = json_bytes(old)
    (root / "supplemental.json").write_bytes(raw)
    accepted = json.loads((root / "accepted-digests.json").read_bytes())
    accepted["supplemental.json"] = digest(raw)
    (root / "accepted-digests.json").write_bytes(json_bytes(accepted))


def vehicle_oracle(quantity: int, capacity: int) -> int:
    """Smallest fleet whose total one-load capacity covers the historical batch."""
    assert quantity > 0 and capacity > 0
    return next(n for n in range(1, 65536) if n * capacity >= quantity)


def cost_oracle(road):
    """Count unique physical road direction pieces independently of path-length formula."""
    tiles = {t.tile_id: t for t in road.input.facts.tiles}
    neighbors = {i: set() for i in road.corridor[1:-1]}
    for a, b in zip(road.corridor, road.corridor[1:]):
        if a in neighbors:
            neighbors[a].add(b)
        if b in neighbors:
            neighbors[b].add(a)
    neighbors[road.depot.front_tile_id].add(road.depot.tile_id)
    for i, values in neighbors.items():
        for j in values:
            assert abs(tiles[i].x - tiles[j].x) + abs(tiles[i].y - tiles[j].y) == 1
    pieces = sum(map(len, neighbors.values()))
    facts = road.input.facts
    infrastructure = (
        pieces * facts.road.road_piece_cost_gbp
        + 2 * facts.road.truck_stop_cost_gbp
        + facts.road.depot_cost_gbp
    )
    engine = next(
        e for e in facts.engines if e.engine_id == road.candidate_provenance[-1].engine_id
    )
    fleet = vehicle_oracle(road.benchmark.quantity, engine.capacity_cargo_units)
    return pieces, infrastructure, fleet * engine.purchase_cost_gbp


def semantic_checks(imported, prepared, road, result):
    assert isinstance(road, ControlledRoadScenario)
    scenario = PlanningScenario.model_validate_json(road.scenario.model_dump_json())
    validate_execution_plan(result.plan, scenario)
    world = road.input.admitted.world
    assert (
        world.structural.complete
        and world.production.complete
        and world.production.qualified_for_planning
    )
    assert world.production.source is world.structural
    assert (
        world.production.source_structural_world_digest == world.structural.structural_world_digest
    )
    assert world.qualified_month_identity.economy_month == 2
    assert world.production.qualification.current_month.month == 3
    assert all(
        r.economy_date_before >= world.production.qualification.current_month.start_date
        for r in world.production.records
    )
    assert world.context.process_identity is world.production.context.process_identity
    assert world.context.connection_identity is world.production.context.connection_identity
    assert len(world.production.records) == 1
    assert road.benchmark.measured_consumption is None
    assert road.benchmark.quantity == world.production.records[0].last_month_produced
    assert road.benchmark.supply.economy_month == 2 and road.benchmark.unit == "cargo_units"
    assert scenario.horizon_days == 31 and scenario.start_date == date(2001, 1, 1)
    assert scenario.cargo_demands[0].source.source_kind == "p08-benchmark-policy"
    assert scenario.world_fingerprint == world_manifest_hash(scenario.world_manifest)
    assert scenario.world_manifest.source_digest == prepared.original_bytes_digest
    assert scenario.world_manifest.source_digest == road.input.manifest.source_digest
    assert road.input.provenance.supplemental_digest == imported.artifact.facts_digest
    assert road.input.provenance.world_observation_digest == world.composition_digest
    assert (
        road.input.provenance.input_manifest_fingerprint
        == prepared.correspondence.world_fingerprint
    )
    assert scenario.world_fingerprint not in (
        world.composition_digest,
        world.structural.structural_world_digest,
    )
    locations = {location.location_id: location for location in scenario.locations}
    candidates = {c.candidate_id: c for c in scenario.infrastructure_candidates}
    demands = {d.demand_id: d for d in scenario.cargo_demands}
    options = {o.option_id: o for o in scenario.fleet_options}
    assert len(locations) == 5 and len(candidates) == 4 and len(options) == 1 and len(demands) == 1
    assert sum(c.kind == ConstructionKind.STATION for c in candidates.values()) == 2
    assert sum(c.kind == ConstructionKind.DEPOT for c in candidates.values()) == 1
    assert sum(c.kind == ConstructionKind.SEGMENT for c in candidates.values()) == 1
    assert len({p.candidate_id for p in road.candidate_provenance}) == 5
    assert all(
        p.provenance_digest == road.input.provenance.digest for p in road.candidate_provenance
    )
    assert all(c.source.source_digest == road.input.provenance.digest for c in candidates.values())
    assert all(
        p.producer_id == road.benchmark.producer.industry_id
        and p.acceptor_id == road.benchmark.acceptor.industry_id
        and p.cargo_id == road.benchmark.cargo.cargo_id
        for p in road.candidate_provenance
    )
    assert road.benchmark.cargo.cargo_id in road.benchmark.producer.produces
    assert road.benchmark.cargo.cargo_id in road.benchmark.acceptor.accepts
    # Independent geometric checks against admitted facts, rather than vacant()/neighbors().
    tiles = {t.tile_id: t for t in road.input.facts.tiles}
    footprint = {road.pickup.tile_id, road.delivery.tile_id, road.depot.tile_id}
    for i in footprint | set(road.corridor):
        t = tiles[i]
        assert t.buildable and t.slope == 0 and t.industry_id is None
        assert not any(
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
    for a, b in zip(road.corridor, road.corridor[1:]):
        assert abs(tiles[a].x - tiles[b].x) + abs(tiles[a].y - tiles[b].y) == 1
        assert tiles[a].min_height == tiles[b].min_height
    for facility, industry, role in (
        (road.pickup, road.benchmark.producer, "pickup"),
        (road.delivery, road.benchmark.acceptor, "delivery"),
    ):
        coverage = next(
            c
            for c in road.input.facts.coverage
            if c.tile_id == facility.tile_id
            and c.industry_id == industry.industry_id
            and c.role == role
        )
        assert coverage.industry_covered and coverage.cargo_id == road.benchmark.cargo.cargo_id
        assert coverage.producer_count > 0 if role == "pickup" else coverage.acceptance_eighths >= 8
    assert road.depot.tile_id not in road.corridor
    assert road.depot.front_tile_id in road.corridor[1:-1]
    for facility in (road.pickup, road.delivery, road.depot):
        a, b = tiles[facility.tile_id], tiles[facility.front_tile_id]
        assert abs(a.x - b.x) + abs(a.y - b.y) == 1 and a.min_height == b.min_height
        dx, dy = {"north": (0, -1), "east": (1, 0), "south": (0, 1), "west": (-1, 0)}[
            facility.orientation
        ]
        assert (a.x + dx, a.y + dy) == (b.x, b.y)
    assert road.corridor[0] == road.pickup.tile_id and road.corridor[-1] == road.delivery.tile_id
    pieces, infrastructure, purchase = cost_oracle(road)
    assert pieces == road.road_pieces
    assert result.metrics.infrastructure_spend_gbp == Decimal(infrastructure)
    assert result.metrics.vehicle_purchase_cost_gbp == Decimal(purchase)
    assert (
        sum((c.estimated_build_cost_gbp for c in candidates.values()), Decimal(0)) == infrastructure
    )
    assert len(result.plan.infrastructure.actions) == 4
    assert len({a.candidate_id for a in result.plan.infrastructure.actions}) == 4
    for action in result.plan.infrastructure.actions:
        assert action.candidate_id in candidates
        assert (
            action.estimated_build_cost_gbp
            == candidates[action.candidate_id].estimated_build_cost_gbp
        )
    assigned = 0
    for group in result.plan.fleet.groups:
        option = options[group.option_id]
        assert isinstance(option, RoadFleetOption)
        assert group.planned_trips_per_vehicle == 1
        assert group.count == vehicle_oracle(
            road.benchmark.quantity, option.vehicle.capacity_cargo_units
        )
        assert group.count == road.fleet_count <= 64
        for route in result.plan.routes:
            assert (
                route.fleet_group_id == group.fleet_group_id and route.route_id in group.route_ids
            )
            assert all(stop.location_id in locations for stop in route.stops)
            for assignment in route.cargo_assignments:
                assert assignment.demand_id in demands and assignment.unit == "cargo_units"
                assert assignment.quantity <= group.count * option.vehicle.capacity_cargo_units
                assigned += assignment.quantity
    assert assigned == road.benchmark.quantity == result.metrics.predicted_delivered_cargo_units
    if scenario.constraints.budget_gbp is not None:
        assert infrastructure + purchase <= scenario.constraints.budget_gbp
    assert result.plan.planner_inputs_digest == scenario_hash(scenario)
    assert result.plan.world_fingerprint == scenario.world_fingerprint
    assert result.metrics.plan_hash == plan_hash(result.plan)
    assert (
        imported.trust
        == road.trust
        == road.input.provenance.trust
        == SourceTrust.CONTROLLED_FIXTURE
    )
    with pytest.raises(PlanningFactError):
        road.require_real_executable_source()


def evidence(imported, prepared, road, result):
    pieces, infrastructure, purchase = cost_oracle(road)
    world = road.input.admitted.world
    return dict(
        schema="p08-controlled-test-verification-v1",
        trust="CONTROLLED_FIXTURE",
        world_observation_digest=world.composition_digest,
        structural_digest=world.structural.structural_world_digest,
        production_digest=world.production.production_digest,
        supplemental_digest=imported.artifact.facts_digest,
        correspondence_digest=digest(canonical_bytes(prepared.correspondence.links)),
        source_bytes_digest=prepared.original_bytes_digest,
        input_manifest_fingerprint=prepared.correspondence.world_fingerprint,
        world_fingerprint=road.scenario.world_fingerprint,
        scenario_hash=scenario_hash(road.scenario),
        plan_hash=plan_hash(result.plan),
        policy_digest=road.input.policy.digest,
        policy_version=road.input.provenance.policy_version,
        qualified_month=json.loads(world.to_bytes())["qualified_month"],
        capture_month="M2",
        od=dict(
            producer=road.benchmark.producer.industry_id,
            acceptor=road.benchmark.acceptor.industry_id,
            cargo=road.benchmark.cargo.cargo_id,
            quantity=road.benchmark.quantity,
            unit="cargo_units",
            meaning=road.benchmark.meaning,
            measured_consumption=None,
        ),
        horizon_days=road.scenario.horizon_days,
        fleet_count=road.fleet_count,
        candidate_counts=dict(stations=2, depots=1, corridors=1, fleet=1),
        candidate_ids=sorted(
            [c.candidate_id for c in road.scenario.infrastructure_candidates]
            + [o.option_id for o in road.scenario.fleet_options]
        ),
        candidate_digest=digest(
            json_bytes([c.model_dump(mode="json") for c in road.scenario.infrastructure_candidates])
        ),
        road_tiles=list(road.corridor),
        road_pieces=pieces,
        search_expansions=road.search_expansions,
        station_pairs=road.station_pairs_examined,
        solver_status="OPTIMAL",
        objective_gbp=str(infrastructure + purchase),
        objective_fixed_point_pence=(infrastructure + purchase) * 100,
        independent_cost_check=True,
        capacity_check=True,
        statuses=[
            "SCHEMA_VALID",
            "CONTROLLED_CANDIDATE_FEASIBLE",
            "P05_MATHEMATICALLY_FEASIBLE",
            "P05_OPTIMAL_SOLUTION_FOUND",
        ],
        real_construction="NOT_PROVEN",
        real_execution="NOT_PROVEN",
        runtime_activity=dict(launches=0, connections=0, real_requests=0),
    )


def test_full_accepted_artifact_pipeline_and_deterministic_record(owned):
    imported, prepared, road = admit(owned)
    assert isinstance(road, ControlledRoadScenario)
    result = optimize_candidate_network(road.scenario)
    semantic_checks(imported, prepared, road, result)
    record = evidence(imported, prepared, road, result)
    assert json_bytes(record) == (FIXTURES / "verification.json").read_bytes()


def test_repeat_full_admission_with_equivalent_artifact_ordering(owned):
    a, p, r = admit(owned)
    assert isinstance(r, ControlledRoadScenario)
    first = optimize_candidate_network(r.scenario)
    before = evidence(a, p, r, first)

    def reverse(d):
        for key in ("tiles", "coverage", "coverage_scopes", "engines"):
            d[key].reverse()

    revise_bundle(owned, reverse)
    b, q, s = admit(owned)
    assert isinstance(s, ControlledRoadScenario)
    second = optimize_candidate_network(s.scenario)
    semantic_checks(b, q, s, second)
    assert a.input_bytes_digest != b.input_bytes_digest
    assert before == evidence(b, q, s, second)
    assert canonical_bytes(first.plan) == canonical_bytes(second.plan)


@pytest.mark.parametrize(
    "quantity,capacity,expected",
    [
        (30, 30, 1),
        (31, 30, 2),
        (1, 30, 1),
        (1920, 30, 64),
        (1921, 30, 65),
        (65535, 65535, 1),
        (65535, 30, 2185),
    ],
)
def test_independent_fleet_oracle_through_admission(tmp_path, quantity, capacity, expected):
    recipe = RECIPE.model_copy(update={"quantity": quantity})
    materialize(tmp_path, recipe)
    revise_bundle(tmp_path, lambda d: d["engines"][0].update(capacity_cargo_units=capacity))
    _, _, road = admit(tmp_path)
    assert vehicle_oracle(quantity, capacity) == expected
    if expected > 64:
        assert isinstance(road, NoRoadScenario) and road.code == RoadOutcome.CAPACITY_INFEASIBLE
    else:
        assert isinstance(road, ControlledRoadScenario)
        solution = optimize_candidate_network(road.scenario)
        assert road.fleet_count == solution.plan.fleet.groups[0].count == expected


def test_search_budget_exhaustion_returns_typed_outcome(owned, monkeypatch):
    import app.planning.p08_road as module

    # Normal 4096 overflow is impossible under 16×256 admission bounds. Fault-inject
    # a smaller internal guard to exercise exhaustion without widening real inputs.
    monkeypatch.setattr(module, "MAX_PATH_EXPANSIONS", 1)
    _, _, road = admit(owned)
    assert isinstance(road, NoRoadScenario)
    assert road.code.value == "SEARCH_LIMIT_EXCEEDED"


@pytest.mark.parametrize(
    "defect", ["byte-digest", "source-digest", "runtime", "content", "coverage"]
)
def test_source_admission_negatives(owned, defect):
    if defect == "byte-digest":
        raw = (owned / "supplemental.json").read_bytes()
        (owned / "supplemental.json").write_bytes(raw + b" ")
    else:

        def damage(d):
            if defect == "source-digest":
                d["source"]["structural_digest"] = "0" * 64
            if defect == "runtime":
                d["source"]["runtime_digest"] = "0" * 64
            if defect == "content":
                d["settings"]["content_digest"] = "0" * 64
            if defect == "coverage":
                d["coverage"].pop()

        revise_bundle(owned, damage)
    with pytest.raises(PlanningFactError):
        admit(owned)


@pytest.mark.parametrize("kind", ["unqualified", "incomplete"])
def test_qualification_gates_prevent_candidate_generation(owned, monkeypatch, kind):
    _, _, road = admit(owned)
    world = road.input.admitted.world
    field = "qualified_for_planning" if kind == "unqualified" else "complete"
    monkeypatch.setattr(IndustryProductionObservation, field, property(lambda self: False))
    with pytest.raises(BridgeProtocolError):
        WorldPlanningObservation(world.structural, world.qualification)
    with pytest.raises(BridgeProtocolError):
        admit(owned, world=world)


def test_production_structural_source_mismatch_is_rejected(owned):
    _, _, road = admit(owned)
    world = road.input.admitted.world
    production = copy(world.production)
    qualification = copy(production.qualification)
    object.__setattr__(qualification, "source_structural_world_digest", "0" * 64)
    object.__setattr__(production, "qualification", qualification)
    verification = copy(world.qualification.verification)
    object.__setattr__(verification, "production", production)
    result = copy(world.qualification)
    object.__setattr__(result, "verification", verification)
    with pytest.raises(BridgeProtocolError, match="source structural"):
        WorldPlanningObservation(world.structural, result)


@pytest.mark.parametrize(
    "empty,quantity,expected",
    [(False, 0, RoadOutcome.ZERO_POSITIVE_SUPPLY), (True, 0, RoadOutcome.NO_ELIGIBLE_BENCHMARK)],
)
def test_valid_qualified_no_scenario_inputs(tmp_path, empty, quantity, expected):
    recipe = RECIPE.model_copy(update={"empty_targets": empty, "quantity": quantity})
    world = materialize(tmp_path, recipe)
    _, _, road = admit(tmp_path)
    assert world.complete and world.production.complete and world.production.qualified_for_planning
    assert isinstance(road, NoRoadScenario) and road.code == expected
    assert not hasattr(road, "scenario")
    assert all(s.quantity == 0 for s in road.input.supplies)


@pytest.mark.parametrize(
    "defect,expected",
    [
        ("stop", RoadOutcome.NO_STATION_PLACEMENT),
        ("catchment", RoadOutcome.MISSING_CATCHMENT),
        ("depot", RoadOutcome.NO_DEPOT_PLACEMENT),
        ("disconnected", RoadOutcome.NO_BOUNDED_CORRIDOR),
        ("occupancy", RoadOutcome.NO_STATION_PLACEMENT),
    ],
)
def test_geometry_negatives_preserve_observation_validity(owned, defect, expected):
    def damage(d):
        if defect == "catchment":
            for c in d["coverage"]:
                c["industry_covered"] = False
        for t in d["tiles"]:
            if defect == "stop" and t["y"] == 2 and t["x"] == RECIPE.producer_id:
                t["buildable"] = False
            if defect == "occupancy" and t["y"] == 2 and t["x"] == RECIPE.producer_id:
                t["road"] = True
            if defect == "depot" and t["y"] != 2:
                t["buildable"] = False
            if defect == "disconnected" and t["x"] == RECIPE.producer_id + 2:
                t["water"] = True

    revise_bundle(owned, damage)
    _, _, road = admit(owned)
    assert isinstance(road, NoRoadScenario) and road.code == expected
    assert road.input.admitted.world.complete


@pytest.mark.parametrize("defect", ["incompatible-cargo", "unavailable", "zero-capacity"])
def test_fleet_admission_negatives(owned, defect):
    def damage(d):
        e = d["engines"][0]
        if defect == "incompatible-cargo":
            e["default_cargo_id"] = RECIPE.other_cargo_id
        if defect == "unavailable":
            e["public_available"] = False
        if defect == "zero-capacity":
            e["capacity_cargo_units"] = 0

    revise_bundle(owned, damage)
    if defect == "zero-capacity":
        with pytest.raises(PlanningFactError):
            admit(owned)
    else:
        _, _, road = admit(owned)
        assert (
            isinstance(road, NoRoadScenario)
            and road.code == RoadOutcome.INVALID_ENGINE_COMPATIBILITY
        )


@pytest.mark.parametrize(
    "defect", ["negative-road", "negative-engine", "mixed-units", "missing-terrain"]
)
def test_invalid_native_fact_values_rejected(owned, defect):
    def damage(d):
        if defect == "negative-road":
            d["road"]["road_piece_cost_gbp"] = -1
        if defect == "negative-engine":
            d["engines"][0]["purchase_cost_gbp"] = -1
        if defect == "mixed-units":
            d["road"]["currency"] = "USD"
        if defect == "missing-terrain":
            del d["tiles"][0]["slope"]

    revise_bundle(owned, damage)
    with pytest.raises(PlanningFactError):
        admit(owned)


def test_real_execution_admission_is_always_blocked(owned):
    _, prepared, road = admit(owned)
    assert isinstance(road, ControlledRoadScenario)
    result = optimize_candidate_network(road.scenario)
    assert result.plan.world_fingerprint == road.scenario.world_fingerprint
    for gate in (
        prepared.correspondence.require_real_executable_source,
        road.input.admitted.require_real_executable_source,
        road.require_real_executable_source,
    ):
        with pytest.raises(PlanningFactError, match="unproven"):
            gate()


def test_at_limit_artifact_is_deterministic(owned):
    _, _, road = admit(owned)
    world = road.input.admitted.world
    d = region_bundle(world, width=16, height=16)
    e = d["engines"][0]
    d["engines"] = [dict(e, engine_id=i) for i in range(32)]
    write_bundle(owned, world, d)
    accepted = json.loads((owned / "accepted-digests.json").read_bytes())
    accepted["supplemental.json"] = digest((owned / "supplemental.json").read_bytes())
    (owned / "accepted-digests.json").write_bytes(json_bytes(accepted))
    a, p, r = admit(owned)
    b, q, s = admit(owned)
    assert isinstance(r, ControlledRoadScenario) and isinstance(s, ControlledRoadScenario)
    assert (
        len(r.input.facts.tiles),
        len(r.input.facts.coverage_scopes),
        len(r.input.facts.coverage),
        len(r.input.facts.engines),
    ) == (256, 2, 512, 32)
    assert r.search_expansions <= 4096 and r.station_pairs_examined <= 16
    assert scenario_hash(r.scenario) == scenario_hash(s.scenario)
    assert canonical_bytes(optimize_candidate_network(r.scenario).plan) == canonical_bytes(
        optimize_candidate_network(s.scenario).plan
    )
    assert (
        MAX_TILES,
        MAX_COVERAGE,
        MAX_ENGINES,
        MAX_STATIONS_PER_ROLE,
        MAX_STATION_PAIRS,
        MAX_PATH_EXPANSIONS,
        MAX_VEHICLES,
    ) == (256, 512, 32, 4, 16, 4096, 64)


@pytest.mark.parametrize("kind", ["tiles", "scopes", "coverage", "engines", "artifact"])
def test_over_limit_rejected_before_search(owned, monkeypatch, kind):
    import app.planning.p08_road as module

    def damage(d):
        if kind == "tiles":
            d["tiles"] *= 9
        if kind == "scopes":
            d["coverage_scopes"].append(d["coverage_scopes"][0])
        if kind == "coverage":
            d["coverage"] *= 9
        if kind == "engines":
            d["engines"] *= 33

    if kind == "artifact":
        (owned / "supplemental.json").write_bytes(b" " * (MAX_ARTIFACT_BYTES + 1))
    else:
        revise_bundle(owned, damage)

    def denied(*args, **kwargs):
        pytest.fail("over-limit artifact reached geometry search")

    monkeypatch.setattr(module, "shortest_path", denied)
    with pytest.raises(PlanningFactError):
        admit(owned)


def test_all_sixteen_station_pairs_are_bounded(owned, monkeypatch):
    import app.planning.p08_road as module

    def damage(d):
        for t in d["tiles"]:
            t["buildable"] = t["y"] == 2
        for c in d["coverage"]:
            x = c["tile_id"] % d["source"]["map_width"]
            c["industry_covered"] = c["tile_id"] // d["source"]["map_width"] == 2 and (
                RECIPE.producer_id - 1 <= x <= RECIPE.producer_id + 2
                if c["role"] == "pickup"
                else RECIPE.acceptor_id - 2 <= x <= RECIPE.acceptor_id + 1
            )
            c["producer_count"] = int(c["industry_covered"] and c["role"] == "pickup")
            c["acceptance_eighths"] = 8 if c["industry_covered"] and c["role"] == "delivery" else 0

    revise_bundle(owned, damage)
    original = module.shortest_path
    work = []

    def search(*args):
        path, count = original(*args)
        work.append(count)
        return path, count

    monkeypatch.setattr(module, "shortest_path", search)
    _, _, road = admit(owned)
    assert isinstance(road, NoRoadScenario)
    assert len(work) <= 16 and sum(work) <= 4096
    # Coincident stops skip search; still prove all sixteen placement combinations
    # are attempted by choosing disjoint four-tile coverage windows in the fixture.
    assert len(work) == 16


def test_budget_boundary_and_fixed_point_objective(owned, monkeypatch):
    from ortools.sat.python import cp_model

    _, _, road = admit(owned)
    assert isinstance(road, ControlledRoadScenario)
    _, infra, purchase = cost_oracle(road)
    expected = infra + purchase
    a, p, r = admit(
        owned, MonthlyBatchPolicy(start_date=date(2001, 1, 1), budget_gbp=str(expected))
    )
    assert isinstance(r, ControlledRoadScenario)
    real_solver = cp_model.CpSolver
    objectives = []

    def solver():
        instance = real_solver()
        solve = instance.solve

        def capture(model, *args, **kwargs):
            assert (
                instance.parameters.num_search_workers == 1 and instance.parameters.random_seed == 0
            )
            status = solve(model, *args, **kwargs)
            if status == cp_model.OPTIMAL:
                objective = model.proto.objective
                assert objective.offset == 0
                objectives.append(
                    sum(
                        coeff * instance.response_proto.solution[i]
                        for i, coeff in zip(objective.vars, objective.coeffs)
                    )
                )
            return status

        instance.solve = capture
        return instance

    monkeypatch.setattr(cp_model, "CpSolver", solver)
    result = optimize_candidate_network(r.scenario)
    semantic_checks(a, p, r, result)
    assert objectives[0] == expected * 100
    assert _cost_units([Decimal("1.234"), Decimal("2.0100")]) == [1234, 2010]
    assert _cost_units([Decimal(expected)]) == [expected * 100]
    _, _, below = admit(
        owned,
        MonthlyBatchPolicy(
            start_date=date(2001, 1, 1), budget_gbp=str(Decimal(expected) - Decimal("0.01"))
        ),
    )
    assert isinstance(below, NoRoadScenario) and below.code == RoadOutcome.COST_INFEASIBLE
    bad = r.scenario.model_copy(
        update={
            "constraints": r.scenario.constraints.model_copy(
                update={"budget_gbp": Decimal(expected) - Decimal("0.01")}
            )
        }
    )
    with pytest.raises(OptimizerFailure) as caught:
        optimize_candidate_network(bad)
    assert caught.value.code == OptimizerFailureCode.BUDGET_INFEASIBLE


def test_running_cost_metadata_does_not_enter_capex_objective(owned):
    _, _, a = admit(owned)
    assert isinstance(a, ControlledRoadScenario)
    first = optimize_candidate_network(a.scenario)
    revise_bundle(
        owned, lambda d: d["engines"][0].update(running_cost_gbp_per_economy_year=1000000)
    )
    _, _, b = admit(owned)
    assert isinstance(b, ControlledRoadScenario)
    second = optimize_candidate_network(b.scenario)
    assert (
        a.scenario.fleet_options[0].vehicle.running_cost_gbp_per_day
        != b.scenario.fleet_options[0].vehicle.running_cost_gbp_per_day
    )
    assert first.metrics.infrastructure_spend_gbp == second.metrics.infrastructure_spend_gbp
    assert first.metrics.vehicle_purchase_cost_gbp == second.metrics.vehicle_purchase_cost_gbp
    assert [g.count for g in first.plan.fleet.groups] == [g.count for g in second.plan.fleet.groups]
    annual = b.input.facts.engines[0].running_cost_gbp_per_economy_year
    with localcontext() as context:
        context.prec = 100
        expected = (Decimal(annual) / Decimal(365)).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_EVEN
        )
    assert b.scenario.fleet_options[0].vehicle.running_cost_gbp_per_day == expected


def test_duplicate_relationship_shares_infrastructure_cost_once(owned):
    _, _, road = admit(owned)
    assert isinstance(road, ControlledRoadScenario)
    scenario = road.scenario
    # A separate controlled P05 stress case, not a second observed supply claim.
    second = scenario.cargo_demands[0].model_copy(update={"demand_id": "second-controlled-batch"})
    scenario = PlanningScenario.model_validate_json(
        scenario.model_copy(
            update={"cargo_demands": (*scenario.cargo_demands, second)}
        ).model_dump_json()
    )
    result = optimize_candidate_network(scenario)
    validate_execution_plan(result.plan, scenario)
    _, infra, purchase = cost_oracle(road)
    assert result.metrics.infrastructure_spend_gbp == infra
    assert result.metrics.vehicle_purchase_cost_gbp == 2 * purchase
    assert len(result.plan.infrastructure.actions) == 4
    assert all(len(a.route_ids) == 2 for a in result.plan.infrastructure.actions)


@pytest.mark.parametrize(
    "defect",
    ["zero-capacity", "missing-station", "duplicate-infrastructure", "invalid-relationship"],
)
def test_p05_semantic_infeasibility_is_typed(owned, defect):
    _, _, road = admit(owned)
    assert isinstance(road, ControlledRoadScenario)
    scenario = road.scenario
    if defect == "zero-capacity":
        option = scenario.fleet_options[0]
        scenario = scenario.model_copy(
            update={
                "fleet_options": (
                    option.model_copy(
                        update={
                            "vehicle": option.vehicle.model_copy(update={"capacity_cargo_units": 0})
                        }
                    ),
                )
            }
        )
    elif defect == "missing-station":
        scenario = scenario.model_copy(
            update={"infrastructure_candidates": scenario.infrastructure_candidates[1:]}
        )
    elif defect == "duplicate-infrastructure":
        scenario = scenario.model_copy(
            update={
                "infrastructure_candidates": (
                    *scenario.infrastructure_candidates,
                    scenario.infrastructure_candidates[-1],
                )
            }
        )
    else:
        candidate = scenario.infrastructure_candidates[-1].model_copy(
            update={"origin_id": "absent-station"}
        )
        scenario = scenario.model_copy(
            update={
                "infrastructure_candidates": (*scenario.infrastructure_candidates[:-1], candidate)
            }
        )
    with pytest.raises(OptimizerFailure):
        optimize_candidate_network(scenario)


def test_solution_dependency_and_duplicate_build_rejected(owned):
    _, _, road = admit(owned)
    assert isinstance(road, ControlledRoadScenario)
    plan = optimize_candidate_network(road.scenario).plan
    action = plan.infrastructure.actions[-1].model_copy(
        update={"depends_on": ("absent-construction",)}
    )
    bad = plan.model_copy(
        update={
            "infrastructure": plan.infrastructure.model_copy(
                update={"actions": (*plan.infrastructure.actions[:-1], action)}
            )
        }
    )
    with pytest.raises(PlanningValidationError):
        validate_execution_plan(bad, road.scenario)
    extra = plan.infrastructure.actions[-1].model_copy(
        update={"construction_id": "duplicate-build"}
    )
    bad = plan.model_copy(
        update={
            "infrastructure": plan.infrastructure.model_copy(
                update={"actions": (*plan.infrastructure.actions, extra)}
            )
        }
    )
    with pytest.raises(PlanningValidationError):
        validate_execution_plan(bad, road.scenario)


def test_genuine_candidate_change_changes_manifest_identity(owned):
    _, _, a = admit(owned)
    assert isinstance(a, ControlledRoadScenario)

    def move(d):
        for c in d["coverage"]:
            if c["role"] == "pickup":
                c["industry_covered"] = c["tile_id"] == a.pickup.tile_id + 1
                c["producer_count"] = int(c["industry_covered"])

    revise_bundle(owned, move)
    _, _, b = admit(owned)
    assert isinstance(b, ControlledRoadScenario)
    assert a.pickup.tile_id != b.pickup.tile_id
    assert a.scenario.world_fingerprint != b.scenario.world_fingerprint
    assert scenario_hash(a.scenario) != scenario_hash(b.scenario)
    assert a.input.manifest.source_digest == b.input.manifest.source_digest


def test_no_native_activity_and_inputs_unchanged(owned, monkeypatch):
    before = {p.name: digest(p.read_bytes()) for p in owned.iterdir() if p.is_file()}

    def denied(*args, **kwargs):
        pytest.fail("controlled integration attempted native activity")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(subprocess, "Popen", denied)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", denied)
    a, p, r = admit(owned)
    assert isinstance(r, ControlledRoadScenario)
    solution = optimize_candidate_network(r.scenario)
    semantic_checks(a, p, r, solution)
    assert before == {p.name: digest(p.read_bytes()) for p in owned.iterdir() if p.is_file()}


@pytest.mark.parametrize(
    "start,horizon",
    [
        (date(2001, 2, 1), 28),
        (date(2000, 2, 1), 29),
        (date(2001, 4, 1), 30),
        (date(2001, 1, 1), 31),
    ],
)
def test_all_month_horizons_preserve_native_supply_period(owned, start, horizon):
    _, _, road = admit(owned, MonthlyBatchPolicy(start_date=start))
    assert isinstance(road, ControlledRoadScenario)
    solution = optimize_candidate_network(road.scenario)
    assert road.scenario.horizon_days == horizon
    assert road.scenario.cargo_demands[0].latest_delivery_day == horizon - 1
    assert road.benchmark.supply.economy_month == 2 and road.benchmark.quantity == 120
    assert solution.plan.fleet.groups[0].count == 4
