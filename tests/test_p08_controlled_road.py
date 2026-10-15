"""15.3 controlled adapter, finite geometry, trust and unmodified P05 integration."""

import ast
import json
import subprocess
import sys
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from test_supplemental_planning_contracts import correspondence, fact_dict, facts
from test_supplemental_planning_contracts import world_for as original_world_for

from app.planning.canonical import canonical_bytes, scenario_hash, world_manifest_hash
from app.planning.domain import ConstructionKind, PlanningScenario
from app.planning.optimizer import OptimizerFailure, optimize_candidate_network
from app.planning.p08_adapter import (
    MAX_PATH_EXPANSIONS,
    AdapterError,
    MonthlyBatchPolicy,
    RoadOutcome,
    adapt_planning_facts,
)
from app.planning.p08_road import (
    ControlledRoadScenario,
    NoRoadScenario,
    generate_road_scenario,
    shortest_path,
    vacant,
)
from app.planning.validation import validate_execution_plan
from app.simulation.openttd.planning_fact_input import ValidatedPlanningFactInput
from app.simulation.openttd.prepared_source_correspondence import SourceTrust
from app.simulation.openttd.supplemental_planning_facts import PlanningFactError


def world_for(**kwargs):
    from test_qualification_coordinator import QualificationWire

    from app.simulation.openttd.cargo_page import CargoCatalogRecord

    quantity = kwargs.pop("quantity", None)

    def record(i, label, freight, effect, classes):
        return CargoCatalogRecord(i, f"{i:08X}", freight, effect, classes)

    def wire(**options):
        result = QualificationWire(**options)
        if quantity is not None:
            result.metrics = (quantity, 0, 0)
        return result

    with (
        patch("test_structural_world.CargoCatalogRecord", side_effect=record),
        patch("test_supplemental_planning_contracts.QualificationWire", side_effect=wire),
    ):
        return original_world_for(**kwargs)


POLICY = MonthlyBatchPolicy(start_date=date(2001, 1, 1))


@pytest.fixture(scope="module")
def world():
    return world_for(accepts=(1,))


def region_facts(w, *, width=6, height=3):
    d = fact_dict(w)
    d["region"] = dict(x=0, y=0, width=width, height=height)
    prototype = d["tiles"][0]
    map_width = w.context.world.map_width
    d["tiles"] = [
        dict(prototype, tile_id=y * map_width + x, x=x, y=y)
        for y in range(height)
        for x in range(width)
    ]
    producer, acceptor = sorted(i.id for i in w.structural.inventory.observation.records)
    cargo = w.production.records[0].cargo_id
    d["coverage_scopes"] = [
        dict(industry_id=producer, cargo_id=cargo, role="pickup"),
        dict(industry_id=acceptor, cargo_id=cargo, role="delivery"),
    ]
    d["coverage"] = [
        dict(
            tile_id=t["tile_id"],
            **s,
            producer_count=1,
            acceptance_eighths=8,
            industry_covered=(
                t["x"] == (0 if s["role"] == "pickup" else width - 1) and t["y"] == height // 2
            ),
        )
        for t in d["tiles"]
        for s in d["coverage_scopes"]
    ]
    return d


def mapped(w, d=None, policy=POLICY, source=None):
    return adapt_planning_facts(
        ValidatedPlanningFactInput(
            w,
            facts(w, d if d is not None else region_facts(w)),
            correspondence(w) if source is None else source,
        ),
        policy,
    )


def generated(w, d=None, policy=POLICY):
    return generate_road_scenario(mapped(w, d, policy))


def success(w, d=None, policy=POLICY):
    r = generated(w, d, policy)
    assert isinstance(r, ControlledRoadScenario), r
    return r


def test_adapter_preserves_qualified_supply_identity_and_period(world):
    m = mapped(world)
    assert m.admitted.world is world
    assert m.facts.source.world_observation_digest == world.composition_digest
    assert m.supplies[0].quantity == world.production.records[0].last_month_produced
    assert m.supplies[0].structural_digest == world.structural.structural_world_digest
    assert m.supplies[0].economy_month == world.qualified_month_identity.economy_month
    assert m.provenance.supplemental_digest == m.facts.semantic_digest


@pytest.mark.parametrize(
    "field",
    [
        "world_observation_digest",
        "structural_digest",
        "production_digest",
        "runtime_digest",
        "configuration_digest",
        "bridge_digest",
        "world_id",
    ],
)
def test_mismatched_admitted_source_rejected(world, field):
    d = region_facts(world)
    d["source"][field] = "conflict" if field == "world_id" else "0" * 64
    with pytest.raises(PlanningFactError, match="identity mismatch"):
        mapped(world, d)


def test_missing_provenance_rejected(world):
    d = region_facts(world)
    del d["source"]["runtime_digest"]
    with pytest.raises(ValidationError):
        mapped(world, d)


def test_unqualified_and_wrong_structural_sources_rejected(world):
    # Corrupt a shallow copy only; every shared historical/controlled source remains immutable.
    for changes in ({"qualification": None}, {"source": replace(world.structural)}):
        production = replace(world.production)
        for k, v in changes.items():
            object.__setattr__(production, k, v)
        verification = replace(world.qualification.verification)
        object.__setattr__(verification, "production", production)
        qualification = replace(world.qualification)
        object.__setattr__(qualification, "verification", verification)
        forged = replace(world)
        object.__setattr__(forged, "qualification", qualification)
        input_value = mapped(world).admitted
        object.__setattr__(input_value, "world", forged)
        with pytest.raises(AdapterError):
            adapt_planning_facts(input_value, POLICY)


def test_typed_input_required(world):
    with pytest.raises(AdapterError):
        adapt_planning_facts(world, POLICY)


def test_equivalent_fact_order_and_decimal_spelling(world):
    d = region_facts(world)
    a = success(world, d, MonthlyBatchPolicy(start_date=date(2001, 1, 1), budget_gbp="100000"))
    for field in ("tiles", "coverage", "coverage_scopes", "engines"):
        d[field].reverse()
    b = success(world, d, MonthlyBatchPolicy(start_date=date(2001, 1, 1), budget_gbp="100000.00"))
    assert a.input.provenance.digest == b.input.provenance.digest
    assert canonical_bytes(a.scenario) == canonical_bytes(b.scenario)
    assert a.candidate_provenance == b.candidate_provenance


def test_zero_production_preserved_and_never_positive_demand():
    w = world_for(zero=True, accepts=(1,))
    m = mapped(w)
    assert all(s.quantity == 0 for s in m.supplies)
    r = generate_road_scenario(m)
    assert isinstance(r, NoRoadScenario)
    assert r.code == RoadOutcome.ZERO_POSITIVE_SUPPLY
    assert not hasattr(r, "scenario")


def test_qualified_empty_targets_remain_valid():
    w = world_for(empty=True)
    m = adapt_planning_facts(ValidatedPlanningFactInput(w, facts(w), correspondence(w)), POLICY)
    assert not m.supplies and w.complete
    r = generate_road_scenario(m)
    assert isinstance(r, NoRoadScenario)
    assert r.code == RoadOutcome.NO_ELIGIBLE_BENCHMARK


def test_od_capability_supply_and_benchmark_meanings(world):
    r = success(world)
    b = r.benchmark
    assert b.supply.quantity == b.quantity > 0
    assert b.cargo.cargo_id in b.producer.produces
    assert b.cargo.cargo_id in b.acceptor.accepts
    assert b.producer.industry_id != b.acceptor.industry_id
    assert b.measured_consumption is None
    assert "benchmark" in b.meaning
    assert r.scenario.cargo_demands[0].source.source_kind == "p08-benchmark-policy"
    assert b.unit == "cargo_units" and b.planned_trips_per_vehicle == 1
    assert r.scenario.horizon_days == 31
    assert r.scenario.cargo_demands[0].latest_delivery_day == 30


def test_calendar_policy_is_configured_not_native(world):
    r = success(world, policy=MonthlyBatchPolicy(start_date=date(2000, 2, 1)))
    assert r.scenario.horizon_days == 29
    assert r.benchmark.supply.economy_month == world.qualified_month_identity.economy_month
    with pytest.raises(AdapterError, match="first day"):
        mapped(world, policy=MonthlyBatchPolicy(start_date=date(2000, 2, 2)))


def test_incompatible_cargo_scope_rejected(world):
    d = region_facts(world)
    for scope in d["coverage_scopes"]:
        scope["cargo_id"] = 9
    for c in d["coverage"]:
        c["cargo_id"] = 9
    with pytest.raises(PlanningFactError, match="relationship"):
        mapped(world, d)


def test_scope_must_include_both_roles(world):
    d = region_facts(world)
    d["coverage_scopes"] = d["coverage_scopes"][:1]
    d["coverage"] = [c for c in d["coverage"] if c["role"] == "pickup"]
    r = generated(world, d)
    assert isinstance(r, NoRoadScenario) and r.code == RoadOutcome.INSUFFICIENT_COVERAGE


def test_all_facilities_and_corridor_are_covered_and_vacant(world):
    r = success(world)
    tiles = {t.tile_id: t for t in r.input.facts.tiles}
    for f in (r.pickup, r.delivery, r.depot):
        assert vacant(tiles[f.tile_id])
        assert f.front_tile_id in r.corridor
        a, b = tiles[f.tile_id], tiles[f.front_tile_id]
        assert abs(a.x - b.x) + abs(a.y - b.y) == 1
    assert r.depot.tile_id not in r.corridor
    assert all(vacant(tiles[i]) for i in r.corridor)
    assert len(set(r.corridor)) == len(r.corridor)
    assert r.search_expansions <= MAX_PATH_EXPANSIONS


@pytest.mark.parametrize("case", ["unavailable", "occupied", "slope", "missing-catchment"])
def test_station_placement_fails_closed(world, case):
    d = region_facts(world)
    for t in d["tiles"]:
        if t["x"] == 0:
            if case == "unavailable":
                t["buildable"] = False
            if case == "occupied":
                t["road"] = True
            if case == "slope":
                t["slope"] = 1
    if case == "missing-catchment":
        for c in d["coverage"]:
            c["industry_covered"] = False
    r = generated(world, d)
    assert isinstance(r, NoRoadScenario)
    assert r.code in (RoadOutcome.MISSING_CATCHMENT, RoadOutcome.NO_STATION_PLACEMENT)


def test_acceptance_threshold_and_industry_membership_required(world):
    for field, bad in (("acceptance_eighths", 7), ("industry_covered", False)):
        d = region_facts(world)
        for c in d["coverage"]:
            if c["role"] == "delivery":
                c[field] = bad
        assert isinstance(generated(world, d), NoRoadScenario)


def test_occupied_depot_and_no_branch_region(world):
    d = region_facts(world)
    for t in d["tiles"]:
        if t["y"] != 1:
            t["rail"] = True
    r = generated(world, d)
    assert isinstance(r, NoRoadScenario) and r.code == RoadOutcome.NO_DEPOT_PLACEMENT


@pytest.mark.parametrize("barrier", ["water", "road", "slope", "height"])
def test_impossible_corridor_does_not_use_unsupported_terrain(world, barrier):
    d = region_facts(world)
    for t in d["tiles"]:
        if t["x"] == 3:
            t[{"height": "min_height"}.get(barrier, barrier)] = (
                2 if barrier in ("height", "slope") else True
            )
    r = generated(world, d)
    assert isinstance(r, NoRoadScenario) and r.code == RoadOutcome.NO_BOUNDED_CORRIDOR


def test_incomplete_or_outside_coverage_rejected(world):
    for case in ("tile", "coverage", "outside"):
        d = region_facts(world)
        if case == "tile":
            d["tiles"].pop()
        if case == "coverage":
            d["coverage"].pop()
        if case == "outside":
            d["coverage"][0]["tile_id"] = 99999
        with pytest.raises(ValueError):
            mapped(world, d)


def test_graph_ties_are_cardinal_and_deterministic(world):
    m = mapped(world)
    tiles = {t.tile_id: t for t in m.facts.tiles}
    width = m.manifest.width_tiles
    a, count = shortest_path(width, width + 2, tiles, width)
    assert a == (width, width + 1, width + 2)
    b, _ = shortest_path(width, 2, dict(reversed(list(tiles.items()))), width)
    c, _ = shortest_path(width, 2, tiles, width)
    assert b == c == (width, 0, 1, 2)
    assert count <= len(tiles)


@pytest.mark.parametrize("case", ["unavailable", "wrong-cargo", "no-engines"])
def test_compatible_engine_required(world, case):
    d = region_facts(world)
    if case == "unavailable":
        d["engines"][0]["public_available"] = False
    if case == "wrong-cargo":
        d["engines"][0]["default_cargo_id"] = 9
    if case == "no-engines":
        d["engines"] = []
    r = generated(world, d)
    assert isinstance(r, NoRoadScenario) and r.code == RoadOutcome.INVALID_ENGINE_COMPATIBILITY


@pytest.mark.parametrize(
    "field,bad",
    [
        ("capacity_cargo_units", 0),
        ("purchase_cost_gbp", -1),
        ("engine_road_type_id", 1),
        ("articulated", True),
    ],
)
def test_invalid_engine_facts_rejected(world, field, bad):
    d = region_facts(world)
    d["engines"][0][field] = bad
    with pytest.raises(ValueError):
        mapped(world, d)


@pytest.mark.parametrize("field", ["purchase_cost_gbp", "running_cost_gbp_per_economy_year"])
def test_missing_engine_cost_rejected(world, field):
    d = region_facts(world)
    del d["engines"][0][field]
    with pytest.raises(ValidationError):
        mapped(world, d)


@pytest.mark.parametrize("field", ["road_piece_cost_gbp", "truck_stop_cost_gbp", "depot_cost_gbp"])
def test_missing_infrastructure_cost_rejected(world, field):
    d = region_facts(world)
    del d["road"][field]
    with pytest.raises(ValidationError):
        mapped(world, d)


@pytest.mark.parametrize(
    "field,bad",
    [
        ("transport_mode", "rail"),
        ("road_type_id", 1),
        ("currency", "USD"),
        ("timekeeping", "wallclock"),
    ],
)
def test_mode_road_currency_and_economy_gates_retained(world, field, bad):
    d = region_facts(world)
    target = (
        d if field == "transport_mode" else d["settings"] if field == "timekeeping" else d["road"]
    )
    target[field] = bad
    with pytest.raises(ValueError):
        mapped(world, d)


def test_capacity_ceil_and_no_supply_clipping(world):
    d = region_facts(world)
    d["engines"][0]["capacity_cargo_units"] = 3
    r = success(world, d)
    assert r.fleet_count == (r.benchmark.quantity + 2) // 3
    assert r.benchmark.quantity == r.benchmark.supply.quantity
    d["engines"][0]["capacity_cargo_units"] = 1
    # Actual fixture quantity is retained; test a forged larger mapping cannot bypass supply.
    m = mapped(world, d)
    forged = replace(m, supplies=(replace(m.supplies[0], quantity=100000), *m.supplies[1:]))
    with pytest.raises(PlanningFactError, match="mapping"):
        generate_road_scenario(forged)


def test_large_qualified_supply_is_not_clipped_to_vehicle_capacity():
    w = world_for(accepts=(1,), quantity=65535)
    r = generated(w)
    assert isinstance(r, NoRoadScenario) and r.code == RoadOutcome.CAPACITY_INFEASIBLE
    assert r.input.supplies[0].quantity == 65535


def test_small_region_keeps_search_work_bounded(world):
    d = region_facts(world, width=16, height=16)
    m = mapped(world, d)
    r = generate_road_scenario(m)
    assert isinstance(r, ControlledRoadScenario)
    assert r.search_expansions <= 16 * 256
    assert r.station_pairs_examined <= 16
    d["region"]["width"] = 17
    with pytest.raises(ValueError):
        mapped(world, d)


def test_native_and_filesystem_operations_are_not_called(world, monkeypatch):
    import socket

    m = mapped(world)

    def denied(*args, **kwargs):
        pytest.fail("pure candidate generation attempted external activity")

    monkeypatch.setattr(subprocess, "Popen", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(Path, "write_bytes", denied)
    monkeypatch.setattr(Path, "write_text", denied)
    assert isinstance(generate_road_scenario(m), ControlledRoadScenario)


def test_duplicate_cargo_labels_rejected():
    w = original_world_for(accepts=(1,))
    with pytest.raises(AdapterError, match="conflicting native cargo labels"):
        mapped(w)


def test_invalid_correspondence_rejected_at_admission(world):
    c = correspondence(world)
    forged = replace(c)
    object.__setattr__(forged, "links", c.links.model_copy(update={"runtime_digest": "0" * 64}))
    input_value = mapped(world).admitted
    object.__setattr__(input_value, "correspondence", forged)
    with pytest.raises(AdapterError) as caught:
        adapt_planning_facts(input_value, POLICY)
    assert caught.value.code == RoadOutcome.INVALID_SOURCE_CORRESPONDENCE


def test_shared_infrastructure_cost_once_and_native_engine_units(world):
    r = success(world)
    solution = optimize_candidate_network(r.scenario)
    actions = solution.plan.infrastructure.actions
    assert len(actions) == 4 and len({a.candidate_id for a in actions}) == 4
    assert r.road_pieces == 2 * (len(r.corridor) - 2) + 1
    expected = Decimal(r.road_pieces * 10 + 2 * 50 + 100)
    assert solution.metrics.infrastructure_spend_gbp == expected
    vehicle = r.scenario.fleet_options[0].vehicle
    assert vehicle.purchase_cost_gbp == Decimal(1000)
    assert vehicle.running_cost_gbp_per_day == Decimal(1)
    assert vehicle.speed_km_per_hour == Decimal(40) * Decimal("1.00584")
    assert solution.metrics.vehicle_purchase_cost_gbp == vehicle.purchase_cost_gbp * r.fleet_count
    assert solution.plan.fleet.groups[0].planned_trips_per_vehicle == 1


def test_road_speed_cap_uses_distinct_native_units(world):
    d = region_facts(world)
    d["road"]["max_speed_native"] = 10
    r = success(world, d)
    assert r.scenario.fleet_options[0].vehicle.speed_km_per_hour == Decimal("20.1168")


def test_budget_and_fixed_point_failures(world):
    r = generated(world, policy=MonthlyBatchPolicy(start_date=date(2001, 1, 1), budget_gbp="1"))
    assert isinstance(r, NoRoadScenario) and r.code == RoadOutcome.COST_INFEASIBLE
    d = region_facts(world)
    d["engines"][0]["purchase_cost_gbp"] = 2**63 - 1
    r = generated(world, d)
    assert isinstance(r, NoRoadScenario) and r.code == RoadOutcome.COST_INFEASIBLE


def test_scenario_p05_compatibility_and_identity_provenance(world):
    r = success(world)
    scenario = PlanningScenario.model_validate_json(r.scenario.model_dump_json())
    solution = optimize_candidate_network(scenario)
    validate_execution_plan(solution.plan, scenario)
    assert scenario.world_fingerprint == world_manifest_hash(scenario.world_manifest)
    assert scenario.world_manifest.source_digest == r.input.manifest.source_digest
    assert scenario.world_fingerprint != world.composition_digest
    assert solution.metrics.predicted_delivered_cargo_units == r.benchmark.quantity
    assert len(scenario.cargo_demands) == 1 and len(scenario.fleet_options) == 1
    assert [c.kind for c in scenario.infrastructure_candidates].count(ConstructionKind.STATION) == 2
    assert len(r.candidate_provenance) == 5
    assert all(p.provenance_digest == r.input.provenance.digest for p in r.candidate_provenance)
    assert all(p.producer_id == r.benchmark.producer.industry_id for p in r.candidate_provenance)
    assert all(p.acceptor_id == r.benchmark.acceptor.industry_id for p in r.candidate_provenance)
    assert scenario_hash(scenario) == scenario_hash(success(world).scenario)


def test_p05_budget_infeasibility_and_positive_demand_invariant_unchanged(world):
    s = success(world).scenario
    bad = s.model_copy(
        update={"constraints": s.constraints.model_copy(update={"budget_gbp": Decimal(0)})}
    )
    with pytest.raises(OptimizerFailure):
        optimize_candidate_network(bad)
    data = json.loads(s.model_dump_json())
    data["cargo_demands"][0]["quantity"] = 0
    with pytest.raises(ValidationError):
        PlanningScenario.model_validate_json(json.dumps(data))


def test_controlled_trust_and_executable_claim_rejected(world):
    r = success(world)
    assert r.classification == "CONTROLLED_PLANNING_SCENARIO"
    assert r.trust == r.input.provenance.trust == SourceTrust.CONTROLLED_FIXTURE
    with pytest.raises(PlanningFactError, match="unproven"):
        r.require_real_executable_source()
    bad = replace(
        r.input,
        provenance=replace(
            r.input.provenance, trust=SourceTrust.REAL_RUNTIME_CORRESPONDENCE_PROVEN
        ),
    )
    with pytest.raises(PlanningFactError):
        generate_road_scenario(bad)


def test_nonempty_conflicting_manifest_never_overwritten(world):
    c = correspondence(world)
    c = replace(c, manifest=c.manifest.model_copy(update={"cargo_types": ("unrelated",)}))
    r = generate_road_scenario(mapped(world, source=c))
    assert isinstance(r, NoRoadScenario) and r.code == RoadOutcome.CONFLICTING_IDENTITIES


def test_input_and_source_bytes_are_unchanged(world):
    m = mapped(world)
    before = (m.facts.to_bytes(), world.to_bytes(), m.manifest.model_dump_json())
    generate_road_scenario(m)
    assert before == (m.facts.to_bytes(), world.to_bytes(), m.manifest.model_dump_json())


def test_import_and_source_boundaries():
    for path in (Path("app/planning/p08_adapter.py"), Path("app/planning/p08_road.py")):
        tree = ast.parse(path.read_text())
        modules = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        assert not any(
            any(
                bad in m
                for bad in (
                    "admin",
                    "gamescript",
                    "probe",
                    "lifecycle",
                    "optimizer",
                    "execution",
                    "preparation.domain",
                )
            )
            for m in modules
        )
    script = """
import sys
import app.planning.p08_adapter
import app.planning.p08_road
bad = [n for n in sys.modules if any(s in n for s in (
    "admin_client", "secure_admin", "gamescript_transport", "preparation.probe",
    "preparation.lifecycle", "preparation.projection", "preparation.domain",
    "runtime.external", "app.planning.optimizer", "ortools"))]
assert not bad, bad
"""
    subprocess.run([sys.executable, "-c", script], check=True)
