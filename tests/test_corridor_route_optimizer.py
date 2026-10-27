"""Offline tests for the production D5 corridor-route optimizer integration.

These tests call the real P05 optimizer and the real D5 wire contract.  They
prove that a bounded map produces a route, that the selected route enters the
plan and request payloads, that route changes change the plan digest, and
that invalid, disconnected, oversized or mismatched routes fail closed.  No
OpenTTD process, AdminPort connection, native mutation or retained-evidence
write is performed.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.simulation.openttd import corridor_freight as cf
from app.simulation.openttd.corridor_freight import (
    FUNDS_AT_D4_CLOSE,
    MAX_FREIGHT_REQUEST_BYTES,
    FreightPlan,
    FreightReadback,
    FreightRequest,
    freight_phase_outcome,
    freight_route_digest,
)
from app.simulation.openttd.corridor_route_optimizer import (
    MAX_OPTIMIZED_ROUTE_TILES,
    RouteOptimizationError,
    RouteOptimizerInput,
    optimize_corridor_route,
    route_from_feasible_tiles,
)
from app.simulation.openttd.proof import corridor_freight_native as work

SEAL = "a" * 64
SCHEDULE = cf.FREIGHT_EXCHANGE_IDS


def route_input(
    *,
    available: tuple[int, ...],
    pickup: int,
    delivery: int,
    depot: int,
) -> RouteOptimizerInput:
    return RouteOptimizerInput(
        map_width=256,
        map_height=256,
        available_tiles=available,
        pickup_candidates=(pickup,),
        delivery_candidates=(delivery,),
        depot_candidates=(depot,),
        vehicle_type="road-truck",
        capacity_cargo_units=20,
        purchase_cost_gbp=Decimal(20),
        running_cost_gbp_per_day=Decimal(0),
        speed_km_per_hour=Decimal(80),
        road_piece_cost_gbp=Decimal(1),
        truck_stop_cost_gbp=Decimal(1),
        depot_cost_gbp=Decimal(1),
        available_funds_gbp=Decimal(FUNDS_AT_D4_CLOSE),
        max_purchase_cost_gbp=Decimal(cf.FREIGHT_MAX_COST),
    )


def make_plan(
    witness: tuple[int, ...],
    *,
    pickup: int,
    pickup_front: int,
    delivery: int,
    delivery_front: int,
    depot: int,
    depot_front: int,
) -> FreightPlan:
    return FreightPlan(
        schema_version=2,
        company=0,
        cargo=1,
        pickup=pickup,
        pickup_front=pickup_front,
        delivery=delivery,
        delivery_front=delivery_front,
        depot=depot,
        depot_front=depot_front,
        pickup_industry=0,
        delivery_industry=1,
        expected_funds=FUNDS_AT_D4_CLOSE,
        max_cost=cf.FREIGHT_MAX_COST,
        witness=witness,
        schedule=SCHEDULE,
    )


# Two distinct feasible bounded maps: the optimizer must select each route.
ROUTE_A = (1000, 1001, 1002, 1003)
DEPOT_A = 1257
ROUTE_B = (2000, 2001, 2002, 2003, 2004)
DEPOT_B = 2257


def test_optimizer_generates_dynamic_feasible_routes():
    first = optimize_corridor_route(
        route_input(
            available=ROUTE_A + (DEPOT_A,),
            pickup=ROUTE_A[0],
            delivery=ROUTE_A[-1],
            depot=DEPOT_A,
        )
    )
    second = optimize_corridor_route(
        route_input(
            available=ROUTE_B + (DEPOT_B,),
            pickup=ROUTE_B[0],
            delivery=ROUTE_B[-1],
            depot=DEPOT_B,
        )
    )
    assert first.route == ROUTE_A
    assert second.route == ROUTE_B
    assert first.route != second.route
    assert first.depot == DEPOT_A and second.depot == DEPOT_B
    assert first.pickup_front == 1001 and first.delivery_front == 1002
    assert second.pickup_front == 2001 and second.delivery_front == 2003
    assert first.plan_digest != second.plan_digest
    assert first.scenario_digest != second.scenario_digest


# Sealed census geometry from the retained Seed-17 network facts.  These are
# real buildable tiles, not synthetic waypoints, and they form several distinct
# corridors between the same endpoints.  The depot touches only the middle row.
CENSUS_FACTS = (
    Path(__file__).resolve().parents[1]
    / "artifacts/demos/playable-demo-698799a2dfb146948fd2983ff2032253/network-facts-0.json"
)
CENSUS_TILES = (43947, 43948, 43949, 44203, 44204, 44205)
CENSUS_PICKUP = 43947
CENSUS_DELIVERY = 43949
CENSUS_DEPOT = 44460


def _census_available() -> tuple[int, ...]:
    """Read the sealed census and prove every route tile is buildable."""
    facts = json.loads(CENSUS_FACTS.read_text())
    buildable = {int(tile["tile_id"]): tile["buildable"] for tile in facts["tiles"]}
    for tile in CENSUS_TILES + (CENSUS_DEPOT,):
        assert buildable[tile] is True, tile
    return CENSUS_TILES + (CENSUS_DEPOT,)


def census_route(*, tile_costs: tuple[tuple[int, Decimal], ...] = ()):
    return route_from_feasible_tiles(
        map_width=256,
        map_height=256,
        available_tiles=_census_available(),
        pickup=CENSUS_PICKUP,
        delivery=CENSUS_DELIVERY,
        depot=CENSUS_DEPOT,
        vehicle_type="road-truck",
        capacity_cargo_units=20,
        purchase_cost_gbp=Decimal(20),
        running_cost_gbp_per_day=Decimal(0),
        speed_km_per_hour=Decimal(80),
        road_piece_cost_gbp=Decimal(1),
        truck_stop_cost_gbp=Decimal(1),
        depot_cost_gbp=Decimal(1),
        available_funds_gbp=Decimal(FUNDS_AT_D4_CLOSE),
        max_purchase_cost_gbp=Decimal(cf.FREIGHT_MAX_COST),
        tile_costs_gbp=tile_costs,
    )


def test_source_backed_map_exposes_competing_feasible_routes():
    """The sealed census set supports several distinct corridors, not one."""
    first = census_route()
    second = census_route()
    assert first.route == second.route
    assert first.candidate_id == second.candidate_id

    # Different source-backed tile costs reveal the competing geometries the
    # bounded k-shortest enumeration found for the same endpoints and depot.
    selections = {
        census_route(tile_costs=costs).route
        for costs in (
            (),
            ((43948, Decimal(1000)),),
            ((44203, Decimal(1000)),),
            ((44205, Decimal(1000)),),
        )
    }
    assert len(selections) >= 3
    for route in selections:
        assert len(set(route)) == len(route) == 5
        assert route[0] == CENSUS_PICKUP and route[-1] == CENSUS_DELIVERY
        assert set(route) <= set(CENSUS_TILES)
        fronts = [tile for tile in route[1:-1] if cf._adjacent(CENSUS_DEPOT, tile)]
        assert fronts == [44204]
    assert first.route in selections


def test_tile_cost_flips_the_objective_and_plan_identity():
    """CAPEX, not path length alone, selects among equally long corridors."""
    default = census_route()
    expensive = census_route(tile_costs=((44203, Decimal(1000)),))
    assert 44203 in default.route
    assert 44203 not in expensive.route
    assert default.route != expensive.route
    assert expensive.route == (43947, 43948, 44204, 44205, 43949)
    # The same-length corridor without the expensive source tile wins on CAPEX.
    assert (default.candidate_id, default.plan_digest) != (
        expensive.candidate_id,
        expensive.plan_digest,
    )


def test_optimizer_selected_route_enters_the_d5_plan_contract():
    assert work.freight_plan().schema_version == 2
    assert work.freight_plan().witness == work.optimized_freight_route().route
    assert work.freight_plan().witness == tuple(work.freight_facts()["witness"])


def test_execution_payload_derives_the_site_route_from_the_plan():
    plan = work.freight_plan()
    state = dict(site=None, engine=None, vehicle=-1)
    site = work._freight_exchange_request(work.freight_schedule()[0], SEAL, plan, state)
    engine = work._freight_exchange_request(work.freight_schedule()[1], SEAL, plan, state)
    assert site.op == "site"
    assert site.route == plan.witness
    assert engine.route is None
    assert len(site.to_bytes()) <= MAX_FREIGHT_REQUEST_BYTES


def test_route_tile_changes_change_the_plan_digest():
    # Same pickup/delivery/depot, different interior geometry. Both routes
    # are cardinally contiguous and touch the depot exactly once.
    straight = make_plan(
        (1100, 1101, 1102, 1103, 1104),
        pickup=1100,
        pickup_front=1101,
        delivery=1104,
        delivery_front=1103,
        depot=845,
        depot_front=1101,
    )
    detour = make_plan(
        (1100, 1101, 1102, 1358, 1359, 1360, 1104),
        pickup=1100,
        pickup_front=1101,
        delivery=1104,
        delivery_front=1360,
        depot=845,
        depot_front=1101,
    )
    assert straight.witness != detour.witness
    assert straight.digest != detour.digest


def test_maximum_route_request_still_fits_the_wire_ceiling():
    route = tuple(range(MAX_OPTIMIZED_ROUTE_TILES))
    request = FreightRequest(
        op="site",
        request_id="site-00",
        plan=SEAL,
        company=0,
        max_cost=cf.FREIGHT_MAX_COST,
        pickup=route[0],
        delivery=route[-1],
        depot=257,
        route=route,
        route_digest=freight_route_digest(route),
    )
    assert len(request.to_bytes()) <= MAX_FREIGHT_REQUEST_BYTES


def test_disconnected_or_depotless_maps_are_refused():
    disconnected = route_input(
        available=(1000, 1001, 1257, 2000, 2001, 2257),
        pickup=1000,
        delivery=2001,
        depot=1257,
    )
    with pytest.raises(RouteOptimizationError, match="no connected"):
        optimize_corridor_route(disconnected)
    depotless = route_input(
        available=ROUTE_A + (9999,),
        pickup=ROUTE_A[0],
        delivery=ROUTE_A[-1],
        depot=9999,
    )
    with pytest.raises(RouteOptimizationError, match="no connected"):
        optimize_corridor_route(depotless)


def test_unbounded_route_inputs_are_refused_before_optimization():
    too_long = tuple(range(MAX_OPTIMIZED_ROUTE_TILES + 1))
    with pytest.raises(RouteOptimizationError, match="no connected|bound"):
        optimize_corridor_route(
            route_input(
                available=too_long + (257,),
                pickup=too_long[0],
                delivery=too_long[-1],
                depot=257,
            )
        )
    with pytest.raises(RouteOptimizationError, match="duplicate"):
        optimize_corridor_route(
            route_input(
                available=(1000, 1000, 1001, 1257),
                pickup=1000,
                delivery=1001,
                depot=1257,
            )
        )


def test_plan_rejects_invalid_optimizer_geometry():
    with pytest.raises(ValidationError, match="cardinally adjacent"):
        make_plan(
            (1000, 1001, 2002, 1003),
            pickup=1000,
            pickup_front=1001,
            delivery=1003,
            delivery_front=2002,
            depot=DEPOT_A,
            depot_front=1001,
        )
    with pytest.raises(ValidationError, match="repeats"):
        make_plan(
            (1000, 1001, 1001, 1003),
            pickup=1000,
            pickup_front=1001,
            delivery=1003,
            delivery_front=1001,
            depot=DEPOT_A,
            depot_front=1001,
        )
    with pytest.raises(ValidationError, match="3..24"):
        make_plan(
            tuple(range(MAX_OPTIMIZED_ROUTE_TILES + 1)),
            pickup=0,
            pickup_front=1,
            delivery=MAX_OPTIMIZED_ROUTE_TILES,
            delivery_front=MAX_OPTIMIZED_ROUTE_TILES - 1,
            depot=257,
            depot_front=1,
        )
    with pytest.raises(ValidationError, match="exactly one"):
        make_plan(
            (1028, 1284, 1540, 1541, 1542, 1286, 1030),
            pickup=1028,
            pickup_front=1284,
            delivery=1030,
            delivery_front=1286,
            depot=1285,
            depot_front=1284,
        )


def test_plan_rejects_fronts_that_do_not_match_the_route():
    with pytest.raises(ValidationError, match="pickup front"):
        make_plan(
            ROUTE_A,
            pickup=ROUTE_A[0],
            pickup_front=1002,
            delivery=ROUTE_A[-1],
            delivery_front=1002,
            depot=DEPOT_A,
            depot_front=1001,
        )
    with pytest.raises(ValidationError, match="delivery front"):
        make_plan(
            ROUTE_A,
            pickup=ROUTE_A[0],
            pickup_front=1001,
            delivery=ROUTE_A[-1],
            delivery_front=1001,
            depot=DEPOT_A,
            depot_front=1001,
        )


def test_request_rejects_route_on_non_site_or_mismatched_endpoints():
    with pytest.raises(ValidationError, match="only the site request"):
        FreightRequest(
            op="engine",
            request_id="engine-00",
            plan=SEAL,
            company=0,
            max_cost=cf.FREIGHT_MAX_COST,
            pickup=1000,
            delivery=1003,
            depot=DEPOT_A,
            route=ROUTE_A,
            route_digest=freight_route_digest(ROUTE_A),
        )
    with pytest.raises(ValidationError, match="endpoints"):
        FreightRequest(
            op="site",
            request_id="site-00",
            plan=SEAL,
            company=0,
            max_cost=cf.FREIGHT_MAX_COST,
            pickup=1000,
            delivery=1004,
            depot=DEPOT_A,
            route=ROUTE_A,
            route_digest=freight_route_digest(ROUTE_A),
        )
    with pytest.raises(ValidationError, match="must carry"):
        FreightRequest(
            op="site",
            request_id="site-00",
            plan=SEAL,
            company=0,
            max_cost=cf.FREIGHT_MAX_COST,
            pickup=1000,
            delivery=1003,
            depot=DEPOT_A,
            route_digest=freight_route_digest(ROUTE_A),
        )
    with pytest.raises(ValidationError, match="route digest"):
        FreightRequest(
            op="site",
            request_id="site-00",
            plan=SEAL,
            company=0,
            max_cost=cf.FREIGHT_MAX_COST,
            pickup=1000,
            delivery=1003,
            depot=DEPOT_A,
            route=ROUTE_A,
            route_digest=freight_route_digest(ROUTE_B),
        )


def _site_readback(plan: FreightPlan, request: FreightRequest) -> FreightReadback:
    return FreightReadback(
        op="site",
        request_id=request.request_id,
        plan=SEAL,
        company=plan.company,
        max_cost=plan.max_cost,
        pickup=plan.pickup,
        delivery=plan.delivery,
        depot=plan.depot,
        route_digest=plan.route_digest,
        status="READY",
        funds=FUNDS_AT_D4_CLOSE,
        cost=0,
        paused=False,
        truck0=True,
        sid0=100,
        truck1=True,
        sid1=101,
        depot_ok=True,
        owner=0,
        pairs_ok=len(plan.witness) - 1,
        pair_total=len(plan.witness) - 1,
        accept=8,
        prod=100,
        wait=5,
        vehicles=0,
    )


def test_stale_route_request_is_rejected_against_the_plan():
    plan = make_plan(
        (1100, 1101, 1102, 1103, 1104),
        pickup=1100,
        pickup_front=1101,
        delivery=1104,
        delivery_front=1103,
        depot=845,
        depot_front=1101,
    )
    other = make_plan(
        (1100, 1101, 1102, 1358, 1359, 1360, 1104),
        pickup=1100,
        pickup_front=1101,
        delivery=1104,
        delivery_front=1360,
        depot=845,
        depot_front=1101,
    )
    request = FreightRequest(
        op="site",
        request_id="site-00",
        plan=SEAL,
        company=plan.company,
        max_cost=plan.max_cost,
        pickup=plan.pickup,
        delivery=plan.delivery,
        depot=plan.depot,
        route=plan.witness,
        route_digest=plan.route_digest,
    )
    readback = _site_readback(plan, request)
    good = freight_phase_outcome([(request, readback)], prelaunch_digest=SEAL, plan=plan)
    assert good["verification"] == "PARTIAL_EXECUTION_EVIDENCE"
    assert good["failed"] is None or "not the planned" not in good["failed"]["error"]
    mismatched = freight_phase_outcome([(request, readback)], prelaunch_digest=SEAL, plan=other)
    assert mismatched["failed"] is not None
    assert "route drifted" in mismatched["failed"]["error"]
