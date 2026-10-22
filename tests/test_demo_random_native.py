"""256x256 preparation and contract tests, with native launches/connections forbidden."""

import json
import socket
import subprocess
from dataclasses import replace

import pytest
import test_freight_network
import test_industry_inventory
import test_structural_world
from test_network_world_preparation import world_vm
from test_supplemental_planning_contracts import facts

from app.demo_random import DemoBudgets, RandomWorldSettings, optimize_bounded, plan_packages
from app.demo_random_native import generation_observation
from app.planning.p08_adapter import adapt_planning_facts
from app.simulation.openttd.freight_planning import compile_freight_network
from app.simulation.openttd.freight_runtime_planning import PlanningReadback
from app.simulation.openttd.planning_fact_input import ValidatedPlanningFactInput
from app.simulation.openttd.proof import freight_delivery as native


@pytest.fixture(autouse=True)
def prohibit_native(monkeypatch):
    original = subprocess.Popen

    def launch(argv, *args, **kwargs):
        if "openttd" in str(argv[0]).lower():
            pytest.fail("native launch forbidden")
        return original(argv, *args, **kwargs)

    def connection(*args, **kwargs):
        pytest.fail("Admin connection forbidden")

    monkeypatch.setattr(subprocess, "Popen", launch)
    monkeypatch.setattr(socket, "create_connection", connection)
    monkeypatch.setattr(native.DeliverySession, "connect_secure", connection)
    monkeypatch.setattr(native.DemoBackend, "launch", connection)


@pytest.mark.parametrize(
    "seed,climate,terrain", [(0, "temperate", 0), (17, "arctic", 2), (54321, "tropic", 5)]
)
def test_complete_random_preparation_is_pristine_native_newgame(tmp_path, seed, climate, terrain):
    settings = RandomWorldSettings(seed=seed, climate=climate, terrain=terrain)
    budgets = DemoBudgets(max_services=5, max_vehicles=5)
    prepared = native.prepare(
        tmp_path / ("playable-demo-" + "a" * 32),
        demo=True,
        planner=True,
        network=True,
        scenario="high-budget-500k",
        random_world=settings.model_dump(),
        random_budget=budgets.model_dump(),
    )
    try:
        native.preflight(prepared)
        metadata = json.loads((prepared.directory / "PRELAUNCH.json").read_bytes())
        assert metadata["world"] == dict(
            source="NATIVE_RANDOM_GENERATOR", seed=seed, width=256, height=256
        )
        assert metadata["budgets"]["selected_services"] == 5
        assert metadata["budgets"]["world_preparation_mutations"] == 0
        assert prepared.spec.argv.count("-g") == 1
        assert prepared.spec.argv[prepared.spec.argv.index("-G") + 1] == str(seed)
        assert not any("heightmap" in a or a.endswith(".sav") for a in prepared.spec.argv)
        assert not (prepared.spec.workspace.root / "heightmap.png").exists()
        assert prepared.spec.workspace.config.read_text().count("[economy]") == 1
        assert not (prepared.directory / "CLAIM.json").exists()
    finally:
        prepared.spec.workspace.close()


def test_random_bridge_does_not_build_or_clear_a_replacement_world():
    vm = world_vm(service_limit=3)
    staged = native.staged_package(
        True,
        True,
        True,
        network_service_limit=5,
        random_budget=DemoBudgets(max_services=5, max_vehicles=5).model_dump(),
    )
    for name in ("delivery.nut", "demo-world.nut", "network-parent.nut", "main.nut"):
        code = staged[name].decode()
        code = "\n".join(line for line in code.splitlines() if not line.startswith("require("))
        vm.execute(code)
    vm.execute("""
        ::GSMap=class extends GSMap {
            static function GetMapSizeX(){return 256;}
            static function GetMapSizeY(){return 256;}
        };
        ::bridge=NetworkFreightProof();bridge.PrepareDemo();
    """)
    assert len(vm.get_roottable()["build_attempts"]) == 0
    assert b"services.len()>=5" in staged["main.nut"]
    assert b"/64" not in staged["network-parent.nut"]
    assert b"q.arg>65535" in staged["network-parent.nut"]


def packages_256(monkeypatch):
    old_world = test_industry_inventory.world_context()
    monkeypatch.setattr(
        test_structural_world,
        "world_context",
        lambda: replace(old_world, map_width=256, map_height=256),
    )
    original = test_industry_inventory.InventoryWire.__init__

    def initialize(self, *args, **kwargs):
        original(self, *args, **kwargs)

        def change(value, _):
            for row in value["industries"]:
                row.update(x=row["id"], y=1, tile=256 + row["id"])

        self.change = change

    monkeypatch.setattr(test_industry_inventory.InventoryWire, "__init__", initialize)
    values = test_freight_network.packages.__wrapped__()
    result = []
    for value in values:
        data = json.loads(value.facts.model_dump_json())
        data["region"]["y"] += 32
        for tile in data["tiles"]:
            tile["y"] += 32
            tile["tile_id"] += 32 * 256
        for coverage in data["coverage"]:
            coverage["tile_id"] += 32 * 256
        result.append(
            adapt_planning_facts(
                ValidatedPlanningFactInput(
                    value.admitted.world,
                    facts(value.admitted.world, data),
                    value.admitted.correspondence,
                ),
                value.policy.model_copy(update={"delivery_batch_limit": 30}),
            )
        )
    return tuple(result)


@pytest.mark.parametrize("service_limit", [1, 2, 3])
def test_observed_p08_p05_compilation_and_replay_above_4095(monkeypatch, service_limit):
    inputs = packages_256(monkeypatch)
    budgets = DemoBudgets(max_services=service_limit, max_vehicles=service_limit)
    network, plan, metadata = plan_packages(inputs, budgets)
    assert len(plan.routes) == service_limit
    assert network.scenario.width_tiles == network.scenario.height_tiles == 256
    services = compile_freight_network(network, plan)
    for _, service in services:
        request = service.selection_request(require_native=False)
        assert min(request.path) > 4095
        assert json.loads(request.to_bytes())["path"] == list(request.path)
        with pytest.raises(ValueError, match="unproven"):
            service.selection_request()  # Controlled facts never gain native authority.
    assert optimize_bounded(network.scenario, budgets) == plan
    assert metadata["selected_services"] == service_limit


def test_generation_readback_matches_requested_settings_and_native_identity():
    settings = RandomWorldSettings(seed=17, terrain=2)
    metadata = dict(random_world=settings.model_dump(), world=dict(seed=17, width=256, height=256))
    runtime = dict(welcome=dict(revision="15.3", seed=17, width=256, height=256))
    read = PlanningReadback(
        protocol=1,
        type="planning_read_result",
        request_id="random-generation",
        kind="generation",
        arg=0,
        src=0,
        dst=0,
        cargo=0,
        before=1,
        after=1,
        data=(0, 2, 1, 2, 256, 256),
    )
    assert generation_observation(metadata, runtime, read)["classification"] == "OBSERVED"
    with pytest.raises(ValueError, match="mismatch"):
        generation_observation(
            metadata, runtime, read.model_copy(update={"data": (0, 5, 1, 2, 256, 256)})
        )


def test_bounded_optimizer_timeout_is_explicit(monkeypatch):
    from app import demo_random
    from app.openttd_demo import SAMPLE
    from app.planning.domain import PlanningScenario

    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(demo_random.subprocess, "run", timed_out)
    scenario = PlanningScenario.model_validate_json(SAMPLE.read_bytes())
    with pytest.raises(ValueError, match="PLANNING_TIMEOUT"):
        optimize_bounded(scenario, DemoBudgets(planning_seconds=1))


def test_random_full_load_policy_accepts_different_service_capacities(monkeypatch):
    from app.planning.optimizer import optimize_candidate_network
    from app.simulation.openttd.freight_native_network import network_from_facts

    inputs = packages_256(monkeypatch)
    raw_facts = []
    for index, value in enumerate(inputs):
        data = json.loads(value.facts.model_dump_json())
        # Distinct engine IDs/capacities from one observed engine catalogue.
        data["engines"] = [
            dict(data["engines"][0], engine_id=7 + n, capacity_cargo_units=capacity)
            for n, capacity in enumerate((15, 30))
        ]
        raw_facts.append(facts(value.admitted.world, data))
    network = network_from_facts(
        inputs[0].admitted.world,
        raw_facts,
        inputs[0].admitted.correspondence,
        inputs[0].policy,
        max_vehicles=3,
        service_batches=True,
    )
    plan = optimize_candidate_network(network.scenario).plan
    services = compile_freight_network(network, plan)
    assert services
    assert all(service.road.benchmark.quantity == service.capacity == 15 for _, service in services)


def test_four_services_exceed_original_three_service_demo(monkeypatch):
    inputs = packages_256(monkeypatch)
    original = inputs[0]
    data = json.loads(original.facts.model_dump_json())
    data["region"]["y"] += 17
    for tile in data["tiles"]:
        tile["y"] += 17
        tile["tile_id"] += 17 * 256
    for coverage in data["coverage"]:
        coverage["tile_id"] += 17 * 256
        coverage["industry_id"] = 40 if coverage["role"] == "pickup" else 17
    for scope in data["coverage_scopes"]:
        scope["industry_id"] = 40 if scope["role"] == "pickup" else 17
    fourth = adapt_planning_facts(
        ValidatedPlanningFactInput(
            original.admitted.world,
            facts(original.admitted.world, data),
            original.admitted.correspondence,
        ),
        original.policy,
    )
    network, plan, _ = plan_packages((*inputs, fourth), DemoBudgets(max_services=4, max_vehicles=4))
    assert len(plan.routes) == len(compile_freight_network(network, plan)) == 4
