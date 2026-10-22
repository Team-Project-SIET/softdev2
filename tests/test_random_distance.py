"""Distance regression over retained native Seed17; all subsequent planning is offline."""

import asyncio
import json
import socket
import subprocess
from dataclasses import replace
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from test_demo_random import observed_world
from test_supplemental_planning_contracts import correspondence, fact_dict, facts

from app.demo_random import (
    DemoBudgets,
    diagnostic_status,
    discover_relationships,
    optimize_bounded,
    planning_diagnostic,
    relationship_region,
)
from app.planning.canonical import plan_hash
from app.planning.p08_adapter import MonthlyBatchPolicy, adapt_planning_facts
from app.planning.p08_road import NoRoadScenario, generate_road_scenario
from app.planning.validation import validate_execution_plan
from app.simulation.openttd.freight_native_network import (
    bounded_relationships,
    network_from_facts,
    plan_network_world,
    replay_network_capture,
)
from app.simulation.openttd.freight_planning import compile_freight_network
from app.simulation.openttd.freight_planning_replay import replay_qualified_world
from app.simulation.openttd.freight_runtime_planning import PlanningReadback, capture_planning_facts
from app.simulation.openttd.planning_fact_input import ValidatedPlanningFactInput
from app.simulation.openttd.proof import freight_delivery as native

RUN = Path("artifacts/demos/playable-demo-b84b9bd854a342f1a86e4ba669d8e450")


@lru_cache
def seed17_world():
    return asyncio.run(
        replay_qualified_world(
            RUN,
            json.loads((RUN / "PRELAUNCH.json").read_bytes()),
            json.loads((RUN / "runtime-identity.json").read_bytes()),
        )
    )


def test_seed17_compatible_discovery_is_independent_of_capture_area():
    actual = discover_relationships(seed17_world(), DemoBudgets())
    assert actual.relationships == (
        (0, 1, 1),
        (3, 2, 7),
        (7, 5, 4),
        (7, 5, 6),
        (8, 4, 3),
        (9, 6, 8),
    )
    assert not actual.truncated
    assert actual.checks == 60


@pytest.fixture(autouse=True)
def no_native(monkeypatch):
    original = subprocess.Popen

    def launch(argv, *args, **kwargs):
        if "openttd" in str(argv[0]).lower():
            pytest.fail("native launch forbidden")
        return original(argv, *args, **kwargs)

    def forbidden(*args, **kwargs):
        pytest.fail("native launch/Admin connection forbidden")

    monkeypatch.setattr(subprocess, "Popen", launch)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(native.DemoBackend, "launch", forbidden)
    monkeypatch.setattr(native.DeliverySession, "connect_secure", forbidden)


def test_seed17_capture_admits_only_450_tile_pair():
    world = seed17_world()
    compatible = discover_relationships(world, DemoBudgets()).relationships
    admitted = []
    for pair in compatible:
        with pytest.raises(ValueError, match="CAPTURE_TILE_BUDGET"):
            relationship_region(world, pair, 256)
        try:
            region = relationship_region(world, pair, 512)
        except ValueError as error:
            assert "CAPTURE_TILE_BUDGET" in str(error)
        else:
            assert region["width"] * region["height"] == 450
            admitted.append(pair)
    assert admitted == [compatible[0]]
    # 260-tile Manhattan pairs remain discoverable; they need unsupported capture area.
    diagnostic = planning_diagnostic(world, json.loads((RUN / "PRELAUNCH.json").read_bytes()))
    assert [p["manhattan_distance"] for p in diagnostic["compatible_relationships"]] == [
        37,
        185,
        260,
        260,
        179,
        94,
    ]


def test_map_edges_clip_padding_without_wrapping_or_missing_tiles():
    world = observed_world(2)
    a, b = world.structural.inventory.observation.records
    a.x, a.y, b.x, b.y = 1, 1, 2, 2
    region = relationship_region(world, (a.id, b.id, 7), 512)
    assert region == dict(x=1, y=1, width=3, height=3, profile="random-rectangle-512-v1")
    a.x, a.y, b.x, b.y = 253, 253, 254, 254
    region = relationship_region(world, (a.id, b.id, 7), 512)
    assert region["x"] + region["width"] == 255
    a.x = 256
    with pytest.raises(ValueError, match="CAPTURE_MAP_BOUND"):
        relationship_region(world, (a.id, b.id, 7), 512)


def test_explicit_discovery_and_capture_budget_exhaustion():
    found = discover_relationships(observed_world(), DemoBudgets(max_relationships=1))
    assert len(found.relationships) == 1 and found.truncated
    found = discover_relationships(observed_world(), DemoBudgets(max_pair_checks=1))
    assert found.status == "SEARCH_LIMIT"
    with pytest.raises(ValueError, match="CAPTURE_PROFILE_UNSUPPORTED"):
        relationship_region(seed17_world(), (0, 1, 1), 65536)


def controlled_flat_coal_data():
    """Retained structure plus EXPLICIT synthetic terrain/catchment/engine assumptions.

    This is a pipeline fixture, never evidence of native Seed17 road feasibility.
    """
    world = seed17_world()
    pair = discover_relationships(world, DemoBudgets()).relationships[0]
    data = fact_dict(world)
    data["region"] = relationship_region(world, pair, 512)
    data["settings"]["generation_seed"] = 17
    r = data["region"]
    prototype = data["tiles"][0]
    data["tiles"] = [
        dict(prototype, x=x, y=y, tile_id=y * 256 + x)
        for y in range(r["y"], r["y"] + r["height"])
        for x in range(r["x"], r["x"] + r["width"])
    ]
    data["coverage_scopes"] = [
        dict(industry_id=pair[0], cargo_id=pair[2], role="pickup"),
        dict(industry_id=pair[1], cargo_id=pair[2], role="delivery"),
    ]
    pickup, delivery = (181, 174), (173, 198)
    data["coverage"] = [
        dict(
            tile_id=t["tile_id"],
            **scope,
            producer_count=1,
            acceptance_eighths=8,
            industry_covered=(t["x"], t["y"])
            == (pickup if scope["role"] == "pickup" else delivery),
        )
        for t in data["tiles"]
        for scope in data["coverage_scopes"]
    ]
    return data


def controlled_input(data=None):
    world = seed17_world()
    source = correspondence(world)
    source = replace(source, manifest=source.manifest.model_copy(update={"seed": 17}))
    value = facts(world, data or controlled_flat_coal_data())
    policy = MonthlyBatchPolicy(
        start_date=date(1950, 1, 1), budget_gbp=Decimal(500000), delivery_batch_limit=30
    )
    return adapt_planning_facts(ValidatedPlanningFactInput(world, value, source), policy)


def test_controlled_larger_capture_p08_p05_selection_and_costs():
    value = controlled_input()
    network = network_from_facts(
        value.admitted.world,
        (value.facts,),
        value.admitted.correspondence,
        value.policy,
        service_batches=True,
    )
    plan = optimize_bounded(network.scenario, DemoBudgets())
    validate_execution_plan(plan, network.scenario)
    assert len(plan.routes) == 1
    assert plan_hash(plan) == plan_hash(optimize_bounded(network.scenario, DemoBudgets()))
    services = compile_freight_network(network, plan)
    request = services[0][1].selection_request(require_native=False)
    assert 25 < len(request.path) <= 47
    assert len(request.to_bytes()) < 1450
    with pytest.raises(ValueError, match="unproven"):
        services[0][1].selection_request()
    assert sum(a.estimated_build_cost_gbp for a in plan.infrastructure.actions) == Decimal(830)
    assert sum(g.count for g in plan.fleet.groups) == 1
    options = {o.option_id: o for o in network.scenario.fleet_options}
    purchase = sum(
        g.count * options[g.option_id].vehicle.purchase_cost_gbp for g in plan.fleet.groups
    )
    assert purchase == Decimal(1000)  # Controlled prices; never observed Seed17 costs.


@pytest.mark.parametrize("terrain", ["tree", "slope", "water", "disconnected"])
def test_unsupported_terrain_rejected_before_selection(terrain):
    data = controlled_flat_coal_data()
    for tile in data["tiles"]:
        if terrain == "slope":
            tile["slope"] = 1
        elif terrain == "disconnected":
            if tile["y"] == 185:
                tile["water"] = True
        else:
            tile[terrain] = True
    value = controlled_input(data)
    road = generate_road_scenario(value, full_load_batch=True)
    assert isinstance(road, NoRoadScenario)
    rejections = []
    with pytest.raises(ValueError, match="NO_FEASIBLE_SERVICES"):
        network_from_facts(
            value.admitted.world,
            (value.facts,),
            value.admitted.correspondence,
            value.policy,
            service_batches=True,
            planning_rejections=rejections,
        )
    assert rejections and rejections[0]["reason"]


def test_capture_requests_complete_450_tiles_and_respect_reply_bounds(tmp_path):
    value = controlled_input()
    data = controlled_flat_coal_data()
    lookup = {t["tile_id"]: t for t in data["tiles"]}
    scopes = {(c["tile_id"], c["role"]): c for c in data["coverage"]}
    (tmp_path / "graphics-identity.json").write_text("{}")
    (tmp_path / "runtime-identity.json").write_text(json.dumps(dict(welcome=dict(seed=17))))
    calls = []

    async def exchange(session, request, directory, response_type):
        calls.append(request)
        if request.kind == "settings":
            row = [1, 0, 0, 3, 0, 10, 50, 100]
        elif request.kind == "engines":
            row = [7]
        elif request.kind == "engine":
            row = [7, 1, 0, 30, 1000, 365, 40]
        else:
            assert request.arg in lookup
            row = (
                [request.arg, 0, 0, 1]
                + [0] * 10
                + [
                    -1,
                    1,
                    8,
                    int(scopes[request.arg, "pickup"]["industry_covered"]),
                    int(scopes[request.arg, "delivery"]["industry_covered"]),
                ]
            )
        date = value.facts.capture_economy_date_before
        payload = dict(
            protocol=1,
            type="planning_read_result",
            request_id=request.request_id,
            kind=request.kind,
            arg=request.arg,
            src=request.src,
            dst=request.dst,
            cargo=request.cargo,
            before=date,
            after=date,
            data=row,
        )
        raw = json.dumps(payload, separators=(",", ":")).encode()
        (directory / (request.request_id + "-request.json")).write_bytes(request.to_bytes())
        (directory / (request.request_id + "-response.json")).write_bytes(raw)
        assert len(raw) <= 512
        return PlanningReadback.parse_for(request, raw)

    backend = NS(health=lambda: None, session=object())
    captured = asyncio.run(
        capture_planning_facts(
            backend,
            NS(directory=tmp_path),
            value.admitted.world,
            read_exchange=exchange,
            retain=False,
            relationship=(0, 1, 1),
            prefix="n0-",
            capture_budget=DemoBudgets(),
        )
    )
    assert len(captured.tiles) == 450 and len(captured.coverage) == 900
    assert backend.planning_read_count == 453
    assert len({q.arg for q in calls if q.kind == "tile"}) == 450
    captured.require_world(value.admitted.world)
    metadata = json.loads((RUN / "PRELAUNCH.json").read_bytes())
    metadata["random_budget"] = DemoBudgets().model_dump()
    relationships, rejected = bounded_relationships(value.admitted.world, metadata)
    (tmp_path / "network-candidates.json").write_text(
        json.dumps(dict(relationships=relationships, rejected=rejected))
    )
    (tmp_path / "network-facts-0.json").write_text(captured.model_dump_json())
    assert replay_network_capture(tmp_path, value.admitted.world, metadata) == [captured]
    (tmp_path / "planning-n0-3-request.json").write_text("{}")
    with pytest.raises(ValueError, match="retained planning request mismatch"):
        replay_network_capture(tmp_path, value.admitted.world, metadata)


def test_no_feasible_planning_still_retains_terminal_and_report(tmp_path, monkeypatch, capsys):
    import app.simulation.openttd.freight_native_network as network

    metadata = json.loads((RUN / "PRELAUNCH.json").read_bytes())
    metadata["random_budget"] = DemoBudgets(capture_tile_limit=256).model_dump()
    (tmp_path / "PRELAUNCH.json").write_text(json.dumps(metadata))
    (tmp_path / "runtime-identity.json").write_bytes((RUN / "runtime-identity.json").read_bytes())

    world = seed17_world()

    async def collect(*args):
        return world

    async def generation(*args, **kwargs):
        return PlanningReadback.model_validate_json(
            (RUN / "random-generation-response.json").read_bytes()
        )

    monkeypatch.setattr(network, "collect_qualified_world", collect)
    monkeypatch.setattr(native, "exchange", generation)
    with pytest.raises(ValueError, match="NO_SUPPORTED_RELATIONSHIP"):
        asyncio.run(plan_network_world(None, NS(directory=tmp_path), None, None, "a" * 64, 30))
    value = json.loads((tmp_path / "planning-diagnostic.json").read_bytes())
    assert len(value["compatible_relationships"]) == 6
    assert value["candidate_count"] == 0 and value["selected_service_count"] is None
    assert len(value["capture_rejections"]) == 6
    assert value["delivery_metrics"] is None and value["financial_results"] is None
    assert diagnostic_status(value) in capsys.readouterr().out
    assert "NO_SUPPORTED_RELATIONSHIP" in (tmp_path / "planning-diagnostic.html").read_text()


def test_qualified_month_failure_retains_failed_diagnostic(tmp_path, monkeypatch, capsys):
    """A failure before any observation-derived facts still publishes fail-closed status."""
    import app.simulation.openttd.freight_native_network as network

    metadata = json.loads((RUN / "PRELAUNCH.json").read_bytes())
    (tmp_path / "PRELAUNCH.json").write_text(json.dumps(metadata))
    (tmp_path / "runtime-identity.json").write_bytes((RUN / "runtime-identity.json").read_bytes())

    async def collect(*args):
        raise RuntimeError("controlled qualification failure")

    monkeypatch.setattr(network, "collect_qualified_world", collect)
    with pytest.raises(RuntimeError, match="controlled qualification failure"):
        asyncio.run(plan_network_world(None, NS(directory=tmp_path), None, None, "a" * 64, 30))
    value = json.loads((tmp_path / "planning-diagnostic.json").read_bytes())
    assert value["status"] == "FAILED" and value["world_observation_digest"] is None
    assert value["candidate_count"] is None and value["capture_rejections"] == []
    assert value["delivery_metrics"] is None
    assert diagnostic_status(value) in capsys.readouterr().out
    assert "controlled qualification failure" in (tmp_path / "planning-diagnostic.html").read_text()


def test_long_candidate_is_not_passed_to_p05_when_executor_cannot_build_it():
    data = controlled_flat_coal_data()
    data["region"] = dict(x=10, y=10, width=128, height=4, profile="random-rectangle-512-v1")
    prototype = data["tiles"][0]
    data["tiles"] = [
        dict(prototype, x=x, y=y, tile_id=y * 256 + x)
        for y in range(10, 14)
        for x in range(10, 138)
    ]
    data["coverage"] = [
        dict(
            tile_id=t["tile_id"],
            **scope,
            producer_count=1,
            acceptance_eighths=8,
            industry_covered=(t["x"], t["y"])
            == ((10, 11) if scope["role"] == "pickup" else (137, 11)),
        )
        for t in data["tiles"]
        for scope in data["coverage_scopes"]
    ]
    value = controlled_input(data)
    road = generate_road_scenario(value, full_load_batch=True)
    assert not isinstance(road, NoRoadScenario)
    assert len(road.corridor) - 2 > 47
    rejected = []
    with pytest.raises(ValueError, match="NO_FEASIBLE_SERVICES"):
        network_from_facts(
            value.admitted.world,
            (value.facts,),
            value.admitted.correspondence,
            value.policy,
            service_batches=True,
            planning_rejections=rejected,
        )
    assert rejected[0]["reason"].startswith("NATIVE_CORRIDOR_BOUND")
