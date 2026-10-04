"""P06 controlled execution of the actual Squirrel code; never starts OpenTTD."""

from decimal import Decimal
from pathlib import Path

import pytest
from squirrel import SQVM

from app.planning.canonical import plan_hash, world_manifest_hash
from app.planning.domain import ConstructionKind, Mode, RailFleetOption, ResolvedSite
from app.planning.execution import (
    CatalogBinding,
    EngineBinding,
    ExecutionBindings,
    execution_payload,
)
from app.planning.optimizer import optimize_candidate_network
from app.planning.transport import _literal, transport_bytes
from tests.test_planning import tiny_scenario

ROOT = Path(__file__).parents[1]


def test_missing_runtime_bindings_rejected_before_mutation():
    import pytest

    from app.planning.execution import ExecutionPreparationError

    scenario = tiny_scenario()
    plan = optimize_candidate_network(scenario).plan
    with pytest.raises(ExecutionPreparationError):
        execution_payload(
            plan, scenario, ExecutionBindings(engines=(), cargo_ids=(), rail_types=())
        )


def executable_scenario(mode=Mode.ROAD, mixed=False):
    scenario = tiny_scenario()
    sites = []
    locations = []
    for location in scenario.locations:
        update = {}
        if "station" in location.location_id:
            update = {"orientation": "east" if location.location_id.endswith("a") else "west"}
            if location.location_id.startswith("rail"):
                update.update(footprint_width_tiles=10, footprint_height_tiles=1)
        elif "depot" in location.location_id:
            from app.planning.domain import Tile

            update = {"orientation": "north", "tile": Tile(x=6, y=5)}
            if location.location_id.startswith("rail"):
                from app.planning.domain import Tile

                update.update(orientation="east", tile=Tile(x=4, y=8))
        location = location.model_copy(update=update)
        locations.append(location)
        site = ResolvedSite.model_validate(
            location.model_dump(exclude={"world_reference", "source"})
        )
        if location.location_id in ("origin", "destination"):
            site = site.model_copy(
                update={
                    "world_kind": "industry",
                    "world_id": 1 if location.location_id == "origin" else 2,
                }
            )
        sites.append(site)
    candidates = []
    for c in scenario.infrastructure_candidates:
        update = {}
        if c.kind is ConstructionKind.STATION and c.mode is Mode.RAIL:
            update = {"footprint_width_tiles": 10, "footprint_height_tiles": 1}
        candidates.append(c.model_copy(update=update))
    from app.planning.domain import Tile

    tiles = set(scenario.world_manifest.buildable_tiles)
    tiles.update(Tile(x=x, y=8) for x in range(4, 29))
    tiles.add(Tile(x=6, y=5))
    options = scenario.fleet_options
    vehicle_types = scenario.world_manifest.vehicle_types
    demand = scenario.cargo_demands[0]
    if mixed:
        rail = options[1]
        assert isinstance(rail, RailFleetOption)
        wagon = rail.wagon_options[0].model_copy(
            update={
                "vehicle_type": "large-wagon",
                "capacity_cargo_units": 50,
                "length_tiles": 2,
                "purchase_cost_gbp": Decimal("140"),
            }
        )
        options = (
            options[0],
            rail.model_copy(update={"wagon_options": rail.wagon_options + (wagon,)}),
        )
        vehicle_types += ("large-wagon",)
        demand = demand.model_copy(update={"quantity": 80})
    manifest = scenario.world_manifest.model_copy(
        update={
            "resolved_sites": tuple(sites),
            "buildable_tiles": tuple(sorted(tiles, key=lambda t: (t.y, t.x))),
            "vehicle_types": vehicle_types,
        }
    )
    scenario = scenario.model_copy(
        update={
            "locations": tuple(locations),
            "infrastructure_candidates": tuple(candidates),
            "world_manifest": manifest,
            "world_fingerprint": world_manifest_hash(manifest),
            "fleet_options": options,
            "cargo_demands": (demand,),
            "constraints": scenario.constraints.model_copy(update={"permitted_modes": (mode,)}),
        }
    )
    plan = optimize_candidate_network(scenario).plan
    bindings = ExecutionBindings(
        engines=(
            EngineBinding(
                vehicle_type="lorry",
                engine_id=10,
                engine_name="lorry",
                mode=Mode.ROAD,
                road_type=0,
                road_station_kind="truck",
            ),
            EngineBinding(
                vehicle_type="engine", engine_id=20, engine_name="engine", mode=Mode.RAIL
            ),
            EngineBinding(
                vehicle_type="wagon",
                engine_id=21,
                engine_name="wagon",
                mode=Mode.RAIL,
                is_wagon=True,
            ),
            EngineBinding(
                vehicle_type="large-wagon",
                engine_id=22,
                engine_name="large-wagon",
                mode=Mode.RAIL,
                is_wagon=True,
            ),
        ),
        cargo_ids=(CatalogBinding(identifier="COAL", runtime_id=0, runtime_name="COAL"),),
        rail_types=(CatalogBinding(identifier="rail", runtime_id=0, runtime_name="Rail"),),
    )
    return plan, scenario, bindings


def run_executor(plan, scenario, bindings, fail=None, fail_number=1, mutate=""):
    vm = SQVM()
    vm.execute(f"::fail_command <- {_literal(fail)}; ::fail_number <- {fail_number};")
    vm.execute(
        "::engine_catalog <- {}; foreach (e in "
        + _literal(
            [
                {
                    "id": 10,
                    "name": "lorry",
                    "mode": "road",
                    "wagon": False,
                    "capacity": 20,
                    "length": 1,
                },
                {
                    "id": 20,
                    "name": "engine",
                    "mode": "rail",
                    "wagon": False,
                    "capacity": 0,
                    "length": 2,
                },
                {
                    "id": 21,
                    "name": "wagon",
                    "mode": "rail",
                    "wagon": True,
                    "capacity": 30,
                    "length": 1,
                },
                {
                    "id": 22,
                    "name": "large-wagon",
                    "mode": "rail",
                    "wagon": True,
                    "capacity": 50,
                    "length": 2,
                },
            ]
        )
        + ") engine_catalog[e.id] <- e;"
    )
    vm.execute((ROOT / "tests/fixtures/p06_command_api.nut").read_text())
    vm.execute(transport_bytes(plan, scenario, plan_hash(plan), bindings).decode())
    vm.execute(mutate)
    vm.execute((ROOT / "app/planning/thin_ai/main.nut").read_text())
    vm.execute((ROOT / "app/planning/thin_ai/execution.nut").read_text())
    vm.execute('try { P03Executor().Start(); } catch(e) { if(e!="CONTROLLED_STOP") throw e; }')
    root = vm.get_roottable()
    return "\n".join(str(s) for s in root["logs"]) + "\n", [str(s) for s in root["calls"]]


def test_road_executes_exact_actions_and_fleet():
    plan, scenario, bindings = executable_scenario()
    log, calls = run_executor(plan, scenario, bindings)
    assert calls[:3] == [
        "road_station|261|262|1|-1",
        "road_station|275|274|1|-1",
        "road_depot|326|262",
    ]
    assert [c for c in calls if c.startswith("road_segment")][1:] == [
        f"road_segment|{x + 256}|{x + 257}" for x in range(5, 19)
    ]
    assert [c for c in calls if c.startswith("purchase")] == ["purchase|326|10|0"] * 5
    assert log.count("P06_EXECUTION_V1|") == 1


def test_rail_exact_mixed_consist_and_orders():
    plan, scenario, bindings = executable_scenario(Mode.RAIL, mixed=True)
    log, calls = run_executor(plan, scenario, bindings)
    assert calls[:3] == [
        "rail_station|517|1|1|10|-1",
        "rail_station|531|1|1|10|-1",
        "rail_depot|516|517",
    ]
    assert [c for c in calls if c.startswith("rail_segment")] == [
        f"rail_segment|{x + 512}|1" for x in range(15, 19)
    ]
    assert [c for c in calls if c.startswith("purchase")] == [
        "purchase|516|20|-1",
        "purchase|516|22|0",
        "purchase|516|21|0",
    ]
    assert [c for c in calls if c.startswith("attach")] == [
        "attach|201|0|200|0",
        "attach|202|0|200|1",
    ]
    assert [c for c in calls if c.startswith("order")] == [
        "order|200|517|16",
        "order|200|531|132",
        "order|200|516|0",
    ]
    assert '"result":"success"' in log


def test_python_independently_accepts_success_and_rejects_duplicate_receipt():
    from app.planning.execution_evidence import ExecutionEvidenceError, parse_execution_evidence

    plan, scenario, bindings = executable_scenario()
    log, _ = run_executor(plan, scenario, bindings)
    receipt = parse_execution_evidence(log, plan, scenario, bindings)
    assert receipt.result == "success"
    assert len(receipt.fleet) == 5
    assert len(receipt.orders) == 5
    terminal = next(line for line in log.splitlines() if "P06_EXECUTION_V1|" in line)
    with pytest.raises(ExecutionEvidenceError):
        parse_execution_evidence(log + terminal + "\n", plan, scenario, bindings)


@pytest.mark.parametrize(
    "mode,mixed,command,stage,reason",
    [
        (Mode.ROAD, False, "road_station", "INFRASTRUCTURE_STARTED", "BUILD_COMMAND_FAILED"),
        (Mode.ROAD, False, "road_segment", "INFRASTRUCTURE_STARTED", "BUILD_COMMAND_FAILED"),
        (Mode.ROAD, False, "purchase", "FLEET_STARTED", "PURCHASE_FAILED"),
        (Mode.ROAD, False, "order", "ORDERS_STARTED", "ORDER_ASSIGNMENT_FAILED"),
        (Mode.RAIL, True, "rail_station", "INFRASTRUCTURE_STARTED", "BUILD_COMMAND_FAILED"),
        (Mode.RAIL, True, "rail_segment", "INFRASTRUCTURE_STARTED", "BUILD_COMMAND_FAILED"),
        (Mode.RAIL, True, "attach", "FLEET_STARTED", "CONSIST_ASSEMBLY_FAILED"),
        (Mode.RAIL, True, "activate", "SETUP_VERIFIED", "ACTIVATION_FAILED"),
    ],
)
def test_command_failure_stops_and_emits_one_partial_receipt(mode, mixed, command, stage, reason):
    from app.planning.execution_evidence import parse_execution_evidence

    plan, scenario, bindings = executable_scenario(mode, mixed)
    log, calls = run_executor(plan, scenario, bindings, command)
    receipt = parse_execution_evidence(log, plan, scenario, bindings)
    assert receipt.result == "failed"
    assert receipt.code == "PARTIAL_EXECUTION"
    assert receipt.failed_stage == stage
    assert receipt.failure_reason == reason
    assert log.count("P06_EXECUTION_V1|") == 1
    assert '"result":"success"' not in log
    assert calls[-1].split("|")[0] == command


def test_runtime_binding_mismatch_fails_without_commands():
    from app.planning.execution_evidence import parse_execution_evidence

    plan, scenario, bindings = executable_scenario()
    log, calls = run_executor(plan, scenario, bindings, mutate='engine_catalog[10].name="wrong";')
    receipt = parse_execution_evidence(log, plan, scenario, bindings)
    assert receipt.code == "PRE_EXECUTION_FAILURE"
    assert receipt.failure_reason == "BINDING_MISMATCH"
    assert calls == []


def test_native_fleet_group_created_and_verified():
    plan, scenario, bindings = executable_scenario()
    log, calls = run_executor(plan, scenario, bindings)
    assert [c for c in calls if c.startswith("group_create")] == ["group_create|1|-1"]
    assert [c for c in calls if c.startswith("group_move")] == [
        f"group_move|300|{v}" for v in range(200, 205)
    ]


def test_world_failure_has_one_pre_execution_receipt():
    from app.planning.execution_evidence import parse_execution_evidence

    plan, scenario, bindings = executable_scenario()
    log, calls = run_executor(plan, scenario, bindings, mutate="::world_location_override <- 999;")
    receipt = parse_execution_evidence(log, plan, scenario, bindings)
    assert receipt.code == "PRE_EXECUTION_FAILURE"
    assert receipt.runtime_world_hash is None
    assert calls == []


def test_out_of_order_action_events_rejected():
    from app.planning.execution_evidence import ExecutionEvidenceError, parse_execution_evidence

    plan, scenario, bindings = executable_scenario()
    log, _ = run_executor(plan, scenario, bindings)
    lines = log.splitlines()
    start = next(i for i, line in enumerate(lines) if '"kind":"action_start"' in line)
    success = next(i for i, line in enumerate(lines) if '"kind":"action_success"' in line)
    lines[start], lines[success] = lines[success], lines[start]
    with pytest.raises(ExecutionEvidenceError):
        parse_execution_evidence("\n".join(lines), plan, scenario, bindings)


def test_rail_exact_four_train_count():
    from app.planning.execution_evidence import parse_execution_evidence

    plan, scenario, bindings = executable_scenario(Mode.RAIL)
    scenario = scenario.model_copy(
        update={
            "constraints": scenario.constraints.model_copy(update={"max_train_length_tiles": 3})
        }
    )
    plan = optimize_candidate_network(scenario).plan
    assert plan.fleet.groups[0].count == 4
    log, calls = run_executor(plan, scenario, bindings)
    receipt = parse_execution_evidence(log, plan, scenario, bindings)
    assert receipt.result == "success"
    assert len(receipt.fleet) == 4
    assert receipt.native_groups[0].vehicle_count == 4
    assert len([c for c in calls if c.startswith("purchase|516|20|")]) == 4
    assert len([c for c in calls if c.startswith("purchase|516|21|")]) == 4
    assert len([c for c in calls if c.startswith("order")]) == 12


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (
            "P03_TRANSPORT.execution.actions.append(P03_TRANSPORT.execution.actions[0]);",
            "DUPLICATE_ACTION",
        ),
        ("P03_TRANSPORT.execution.actions.reverse();", "DEPENDENCY_FAILED"),
        ("::slope_override <- 1;", "UNSUPPORTED_GEOMETRY"),
    ],
)
def test_preflight_rejects_without_mutation(mutation, reason):
    from app.planning.execution_evidence import parse_execution_evidence

    plan, scenario, bindings = executable_scenario()
    log, calls = run_executor(plan, scenario, bindings, mutate=mutation)
    receipt = parse_execution_evidence(log, plan, scenario, bindings)
    assert receipt.code == "PRE_EXECUTION_FAILURE"
    assert receipt.failure_reason == reason
    assert calls == []


@pytest.mark.parametrize(
    "mode,command,number",
    [
        (Mode.ROAD, "road_depot", 1),
        (Mode.RAIL, "rail_depot", 1),
        (Mode.RAIL, "purchase", 2),
        (Mode.ROAD, "order", 2),
        (Mode.ROAD, "group_create", 1),
        (Mode.ROAD, "group_move", 1),
    ],
)
def test_partial_failure_retains_entities_and_exact_failed_command(mode, command, number):
    from app.planning.execution_evidence import parse_execution_evidence

    plan, scenario, bindings = executable_scenario(mode, mixed=(mode == Mode.RAIL))
    log, calls = run_executor(plan, scenario, bindings, command, number)
    receipt = parse_execution_evidence(log, plan, scenario, bindings)
    assert receipt.code == "PARTIAL_EXECUTION"
    assert calls[-1].split("|")[0] == command
    assert not any(c.startswith("activate") for c in calls)
    if mode == Mode.RAIL and command == "purchase":
        assert len(receipt.created_vehicles) == 1
        assert receipt.created_vehicles[0].role == "locomotive"
    if command == "order":
        assert receipt.orders[0].targets == (261,)
        assert receipt.orders[0].assigned is False


def test_deterministic_evidence_and_p03_transport_only_mode():
    from app.planning.execution_evidence import parse_execution_evidence
    from app.planning.setup_evidence import parse_setup_evidence

    plan, scenario, bindings = executable_scenario()
    first = run_executor(plan, scenario, bindings)
    assert run_executor(plan, scenario, bindings) == first
    parse_execution_evidence(first[0], plan, scenario, bindings)
    log, calls = run_executor(plan, scenario, None)
    assert parse_setup_evidence(log, plan, scenario).status == "accepted"
    assert "P06_" not in log
    assert calls == []


def alter_receipt(log, change):
    import json

    lines = log.splitlines()
    for i, line in enumerate(lines):
        if "P06_EXECUTION_V1|" in line:
            prefix, raw = line.split("P06_EXECUTION_V1|", 1)
            body = json.loads(raw)
            change(body)
            lines[i] = prefix + "P06_EXECUTION_V1|" + json.dumps(body, separators=(",", ":"))
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize(
    "field",
    [
        "plan_hash",
        "runtime_world_hash",
        "action_id",
        "action_tiles",
        "vehicle_id",
        "engine_id",
        "orders",
        "missing_vehicles",
        "stage",
    ],
)
def test_python_rejects_wrong_identity_actions_entities_and_orders(field):
    from app.planning.execution_evidence import ExecutionEvidenceError, parse_execution_evidence

    plan, scenario, bindings = executable_scenario()
    log, _ = run_executor(plan, scenario, bindings)

    def change(r):
        if field in ("plan_hash", "runtime_world_hash"):
            r[field] = "f" * 64
        elif field == "action_id":
            r["actions"][0]["construction_id"] = "wrong-action"
        elif field == "action_tiles":
            r["actions"][0]["tiles"] = [999]
        elif field == "vehicle_id":
            r["fleet"][0]["vehicle_id"] = 999
        elif field == "engine_id":
            r["created_vehicles"][0]["engine_id"] = 999
        elif field == "orders":
            r["orders"][0]["targets"][0] = 999
        elif field == "missing_vehicles":
            r["created_vehicles"] = []
        else:
            r["stages"][2] = "FLEET_STARTED"

    with pytest.raises(ExecutionEvidenceError):
        parse_execution_evidence(alter_receipt(log, change), plan, scenario, bindings)


def test_wrong_failed_entity_rejected_even_when_event_matches():
    from app.planning.execution_evidence import ExecutionEvidenceError, parse_execution_evidence

    plan, scenario, bindings = executable_scenario()
    log, _ = run_executor(plan, scenario, bindings, "purchase")
    wrong = log.replace(plan.fleet.groups[0].fleet_group_id, "unknown-group")
    with pytest.raises(ExecutionEvidenceError):
        parse_execution_evidence(wrong, plan, scenario, bindings)


def test_unsupported_service_rejected_before_staging(tmp_path):
    import hashlib

    from app.planning.domain import LocationKind, PlanningLocation, RouteStop, StopRole, Tile
    from app.planning.execution import ExecutionPreparationError
    from app.planning.transport import materialize_plan

    plan, scenario, bindings = executable_scenario()
    location = PlanningLocation(
        location_id="service",
        tile=Tile(x=30, y=4),
        kind=LocationKind.SERVICE_WAYPOINT,
        permitted_modes=(Mode.ROAD,),
    )
    manifest = scenario.world_manifest.model_copy(
        update={
            "resolved_sites": scenario.world_manifest.resolved_sites
            + (
                ResolvedSite.model_validate(
                    location.model_dump(exclude={"source", "world_reference"})
                ),
            ),
            "source_digest": hashlib.sha256(b"world").hexdigest(),
        }
    )
    scenario = scenario.model_copy(
        update={
            "locations": scenario.locations + (location,),
            "world_manifest": manifest,
            "world_fingerprint": world_manifest_hash(manifest),
        }
    )
    route = plan.routes[0]
    route = route.model_copy(
        update={
            "stops": route.stops[:1]
            + (RouteStop(location_id="service", role=StopRole.SERVICE),)
            + route.stops[1:]
        }
    )
    plan = plan.model_copy(
        update={
            "routes": (route,),
            "world_fingerprint": scenario.world_fingerprint,
            "validation": plan.validation.model_copy(
                update={"validated_world_fingerprint": scenario.world_fingerprint}
            ),
        }
    )
    world = tmp_path / "world.sav"
    world.write_bytes(b"world")
    workspace = tmp_path / "package"
    workspace.mkdir(mode=0o700)
    with pytest.raises(ExecutionPreparationError, match="SERVICE"):
        materialize_plan(plan, scenario, plan_hash(plan), workspace, world, bindings)
    assert list(workspace.iterdir()) == []


def test_execution_package_preserves_p03_shape_and_tamper_checks(tmp_path):
    import hashlib

    from app.planning.transport import PlanTransportError, materialize_plan, verify_staged_package

    plan, scenario, bindings = executable_scenario()
    world = tmp_path / "world.sav"
    world.write_bytes(b"world")
    manifest = scenario.world_manifest.model_copy(
        update={"source_digest": hashlib.sha256(b"world").hexdigest()}
    )
    scenario = scenario.model_copy(
        update={"world_manifest": manifest, "world_fingerprint": world_manifest_hash(manifest)}
    )
    plan = optimize_candidate_network(scenario).plan
    workspace = tmp_path / "package"
    workspace.mkdir(mode=0o700)
    receipt = materialize_plan(plan, scenario, plan_hash(plan), workspace, world, bindings)
    assert {p.name for p in receipt.ai_directory.iterdir()} == {"info.nut", "main.nut", "plan.nut"}
    verify_staged_package(receipt)
    main = receipt.ai_directory / "main.nut"
    assert "class P06Execution" in main.read_text()
    main.write_text(main.read_text() + "\n//tampered\n")
    with pytest.raises(PlanTransportError):
        verify_staged_package(receipt)


def test_unsupported_orientation_and_station_axis_rejected():
    from app.planning.execution import ExecutionPreparationError

    plan, scenario, bindings = executable_scenario(Mode.RAIL)
    candidates = tuple(
        c.model_copy(update={"orientation": "north"}) if c.candidate_id == "rail-station-a" else c
        for c in scenario.infrastructure_candidates
    )
    scenario = scenario.model_copy(update={"infrastructure_candidates": candidates})
    with pytest.raises(ExecutionPreparationError):
        execution_payload(plan, scenario, bindings)


def test_executor_has_no_optimization_or_database_runtime_imports():
    import subprocess
    import sys

    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
import app.planning.execution
import app.planning.execution_evidence
prefixes = ("ortools", "sqlalchemy", "openttdlab", "app.database",
            "app.experiments", "app.simulation", "app.planning.optimizer")
assert not any(n.startswith(prefixes) for n in sys.modules)
""",
        ],
        check=True,
    )
    source = (ROOT / "app/planning/thin_ai/execution.nut").read_text()
    for prohibited in (
        "BuildBridge",
        "BuildTunnel",
        "Terraform",
        "DemolishTile",
        "AIEngineList",
        "Pathfinder",
        "Random",
    ):
        assert prohibited not in source


def test_receipt_size_is_bounded_before_staging():
    from app.planning.execution import ExecutionPreparationError

    _, scenario, bindings = executable_scenario()
    scenario = scenario.model_copy(
        update={
            "cargo_demands": (scenario.cargo_demands[0].model_copy(update={"quantity": 20000}),),
            "constraints": scenario.constraints.model_copy(update={"budget_gbp": None}),
        }
    )
    plan = optimize_candidate_network(scenario).plan
    with pytest.raises(ExecutionPreparationError, match="evidence capacity"):
        execution_payload(plan, scenario, bindings)


def test_native_capacity_mismatch_stops_before_orders():
    from app.planning.execution_evidence import parse_execution_evidence

    plan, scenario, bindings = executable_scenario()
    log, calls = run_executor(plan, scenario, bindings, mutate="engine_catalog[10].capacity=19;")
    receipt = parse_execution_evidence(log, plan, scenario, bindings)
    assert receipt.code == "PARTIAL_EXECUTION"
    assert receipt.failure_reason == "VERIFICATION_FAILED"
    assert not any(c.startswith(("order|", "activate|")) for c in calls)


def test_execution_does_not_mutate_scenario_or_plan():
    plan, scenario, bindings = executable_scenario(Mode.RAIL, mixed=True)
    original = (plan.model_dump_json(), scenario.model_dump_json())
    run_executor(plan, scenario, bindings)
    assert (plan.model_dump_json(), scenario.model_dump_json()) == original


def test_shared_actions_execute_once_with_canonical_fleet_order():
    from app.planning.execution_evidence import parse_execution_evidence

    _, scenario, bindings = executable_scenario()
    demand = scenario.cargo_demands[0]
    scenario = scenario.model_copy(
        update={"cargo_demands": (demand, demand.model_copy(update={"demand_id": "second"}))}
    )
    plan = optimize_candidate_network(scenario).plan
    plan = plan.model_copy(
        update={
            "fleet": plan.fleet.model_copy(update={"groups": tuple(reversed(plan.fleet.groups))})
        }
    )
    log, calls = run_executor(plan, scenario, bindings)
    receipt = parse_execution_evidence(log, plan, scenario, bindings)
    assert receipt.result == "success"
    assert len(receipt.actions) == 4
    assert all(len(a.route_ids) == 2 for a in plan.infrastructure.actions)
    assert len([c for c in calls if c.startswith("road_station|")]) == 2
    assert len([c for c in calls if c.startswith("road_depot|")]) == 1
    assert [g.group_id for g in receipt.native_groups] == sorted(
        g.fleet_group_id for g in plan.fleet.groups
    )


def test_partial_failure_cannot_be_relabelled_pre_execution():
    from app.planning.execution_evidence import ExecutionEvidenceError, parse_execution_evidence

    plan, scenario, bindings = executable_scenario()
    log, _ = run_executor(plan, scenario, bindings, "road_station")
    wrong = alter_receipt(log, lambda r: r.update(code="PRE_EXECUTION_FAILURE"))
    with pytest.raises(ExecutionEvidenceError, match="mutation"):
        parse_execution_evidence(wrong, plan, scenario, bindings)


def test_success_cannot_include_action_failure_evidence():
    import json

    from app.planning.execution_evidence import ExecutionEvidenceError, parse_execution_evidence

    plan, scenario, bindings = executable_scenario()
    log, _ = run_executor(plan, scenario, bindings)
    lines = log.splitlines()
    i = next(i for i, line in enumerate(lines) if '"kind":"action_success"' in line)
    prefix, raw = lines[i].split("P06_EVENT_V1|", 1)
    event = json.loads(raw)
    event["kind"] = "action_failure"
    lines.insert(i, prefix + "P06_EVENT_V1|" + json.dumps(event))
    with pytest.raises(ExecutionEvidenceError, match="success after failure"):
        parse_execution_evidence("\n".join(lines), plan, scenario, bindings)


def test_delayed_fleet_activation_is_rejected_before_staging():
    from app.planning.execution import ExecutionPreparationError

    plan, scenario, bindings = executable_scenario()
    group = plan.fleet.groups[0].model_copy(update={"start_day": 1})
    plan = plan.model_copy(update={"fleet": plan.fleet.model_copy(update={"groups": (group,)})})
    with pytest.raises(ExecutionPreparationError, match="start_day"):
        execution_payload(plan, scenario, bindings)


def test_road_station_binding_must_match_native_cargo_class():
    from app.planning.execution_evidence import parse_execution_evidence

    plan, scenario, bindings = executable_scenario()
    engine = bindings.engines[0].model_copy(update={"road_station_kind": "bus"})
    bindings = bindings.model_copy(update={"engines": (engine,) + bindings.engines[1:]})
    log, calls = run_executor(plan, scenario, bindings)
    receipt = parse_execution_evidence(log, plan, scenario, bindings)
    assert receipt.code == "PRE_EXECUTION_FAILURE"
    assert receipt.failure_reason == "BINDING_MISMATCH"
    assert calls == []


def test_group_verification_uses_real_get_group_id_api():
    from app.planning.execution_evidence import parse_execution_evidence

    plan, scenario, bindings = executable_scenario()
    log, calls = run_executor(plan, scenario, bindings)
    receipt = parse_execution_evidence(log, plan, scenario, bindings)
    assert receipt.result == "success"
    native_id = receipt.native_groups[0].runtime_id
    assert [c for c in calls if c.startswith("group_readback|")] == [
        f"group_readback|{v.vehicle_id}|{native_id}" for v in receipt.fleet
    ]


def test_nonexistent_get_group_fails_faithful_fake(monkeypatch):
    from app.planning.execution_evidence import parse_execution_evidence

    original = Path.read_text

    def old_source(path, *args, **kwargs):
        text = original(path, *args, **kwargs)
        if path.name == "execution.nut":
            return text.replace("AIVehicle.GetGroupID(", "AIVehicle.GetGroup(")
        return text

    stub = (ROOT / "tests/fixtures/p06_command_api.nut").read_text()
    assert "function GetGroup(" not in stub
    assert "function GetGroupID(" in stub
    monkeypatch.setattr(Path, "read_text", old_source)
    plan, scenario, bindings = executable_scenario()
    log, calls = run_executor(plan, scenario, bindings)
    receipt = parse_execution_evidence(log, plan, scenario, bindings)
    assert receipt.result == "failed"
    assert receipt.code == "PARTIAL_EXECUTION"
    assert receipt.failed_stage == "SETUP_VERIFIED"
    assert receipt.failure_reason == "UNEXPECTED_ERROR"
    assert not any(c.startswith("activate|") for c in calls)
