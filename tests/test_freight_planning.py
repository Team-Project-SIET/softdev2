"""Existing controlled WPO -> P08 -> P05 -> checked freight intent, with no native activity."""

import pytest
from test_p08_controlled_e2e import RECIPE, admit, materialize

from app.planning.optimizer import optimize_candidate_network
from app.planning.p08_road import ControlledRoadScenario
from app.simulation.openttd.freight_planning import compile_freight_service
from app.simulation.openttd.supplemental_planning_facts import PlanningFactError


def test_planner_decisions_execute_through_existing_freight_receipt(tmp_path, monkeypatch):
    """Controlled WPO/P08/P05 -> exact native admission -> existing delivery stages."""
    import json
    import socket
    import subprocess
    from dataclasses import replace
    from datetime import date

    from app.planning.p08_adapter import MonthlyBatchPolicy, adapt_planning_facts
    from app.planning.p08_road import generate_road_scenario
    from app.simulation.openttd.freight_delivery import (
        DeliveryReadback,
        verify_delivery,
        verify_snapshot,
    )
    from app.simulation.openttd.freight_delivery import admit as admit_native
    from app.simulation.openttd.proof import freight_delivery as proof
    from tests.test_freight_delivery import call, delivery_vm

    def forbidden(*args, **kwargs):
        pytest.fail("controlled integration launched or connected a native runtime")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    world = materialize(tmp_path)
    _, _, original = admit(tmp_path, world=world)
    admitted = original.input.admitted
    engines = tuple(
        e.model_copy(update={"capacity_cargo_units": 20, "purchase_cost_gbp": 5000})
        for e in admitted.supplemental.engines
    )
    facts = admitted.supplemental.model_copy(update={"engines": engines})
    policy = MonthlyBatchPolicy(start_date=date(1950, 1, 1), delivery_batch_limit=20)
    road = generate_road_scenario(
        adapt_planning_facts(replace(admitted, supplemental=facts), policy)
    )
    assert isinstance(road, ControlledRoadScenario)
    result = optimize_candidate_network(road.scenario)
    service = compile_freight_service(road, result.plan)
    assert world.production.records[0].last_month_produced == 120
    assert (
        road.benchmark.quantity == 20
        and road.benchmark.meaning == "policy-capped-qualified-supply-demonstration"
    )
    with pytest.raises(PlanningFactError, match="unproven"):
        service.selection_request()
    request = service.selection_request(require_native=False)
    vm = delivery_vm()
    staged = proof.staged_package(True, True)
    vm.execute(staged["delivery.nut"].decode().replace('require("vehicle.nut");', ""))
    vm.execute(staged["demo-world.nut"].decode().replace('require("delivery.nut");', ""))
    vm.execute(
        staged["main.nut"]
        .decode()
        .replace('require("demo-world.nut");', "")
        .replace('require("qualification.nut");', "")
    )
    vm.execute("""
        GSMap.DistanceManhattan <- function(a,b){return abs(a%64-b%64)+abs(a/64-b/64);};
        GSEngine.IsBuildable <- function(e){return e==23;};
        GSEngine.IsValidEngine <- function(e){return e==23;};
        GSVehicle.GetEngineType <- function(v){return 23;};
        GSIndustry.IsValidIndustry <- function(i){return i==11||i==16;};
        GSIndustry.GetIndustryID <- function(t){return t==75?11:(t==80?16:-1);};
        GSIndustry.GetLocation <- function(i){return i==11?75:80;};
        GSIndustry.GetLastMonthProduction <- function(i,c){return i==11&&c==3?120:0;};
        GSIndustry.IsCargoAccepted <- function(i,c){return i==16&&c==3?1:0;};
        GSCargoMonitor.GetIndustryPickupAmount <- function(c,k,i,keep){
            if(i!=11)throw "wrong producer";return keep?0:20;};
        GSCargoMonitor.GetIndustryDeliveryAmount <- function(c,k,i,keep){
            if(i!=16)throw "wrong acceptor";return keep?0:20;};
        ::bridge=PlannerFreightProof();
    """)
    # Invalid route/depot arguments reject before invoking the distance API.
    vm.execute("""
        bridge.planner_selected={a=[0,1,1,23,65,-1,68,67,69,67],path=[-1,67],depot_front=67};
        if(bridge.Select()!="PLANNER_TOPOLOGY_REJECTED")throw "invalid route tile admitted";
        bridge.planner_selected={a=[0,1,1,23,65,66,68,67,-1,67],path=[66,67],depot_front=67};
        if(bridge.Select()!="PLANNER_DEPOT_REJECTED")throw "invalid depot tile admitted";
        bridge.planner_selected=null;
    """)
    vm.execute("bridge.Handle(" + request.to_bytes().decode() + ");")
    table = vm.get_roottable()["replies"][0]
    data = {
        str(k): str(table[k])
        if str(k) in ("op", "request_id", "plan", "status")
        else [int(v) for v in table[k]]
        if str(k) in ("a", "f", "s")
        else int(table[k])
        for k in table.keys()
    }
    inspected = DeliveryReadback.parse_for(request.admission_request, json.dumps(data).encode())
    native = admit_native(
        inspected, "a" * 64, "b" * 64, None, selection_digest=service.execution_plan_digest
    )
    assert native.a == request.a
    baseline = None
    for i in range(10):
        assert call(vm, "build", f"build-{i}", i, native.digest).status == "BUILT"
        read = call(vm, "read", f"read-{i}", i, native.digest)
        verify_snapshot(native, read)
        if i == 8:
            baseline = read
    observations = [call(vm, "observe", f"observe-{i}", i, native.digest) for i in range(4)]
    final = call(vm, "finish", "finish-1", 0, native.digest)
    receipt = verify_delivery(native, baseline, observations, final)
    assert (receipt["source"], receipt["destination"], receipt["engine"], receipt["delivered"]) == (
        11,
        16,
        23,
        20,
    )
    assert receipt["payment_income"] == 500


def test_planning_reads_reject_oversize_duplicates_identity_and_shapes():
    import json

    from app.simulation.openttd.freight_runtime_planning import PlanningRead, PlanningReadback

    q = PlanningRead(request_id="planning-0", kind="tile", arg=139, src=11, dst=16, cargo=3)
    value = q.model_dump(mode="json") | dict(
        type="planning_read_result", before=700000, after=700000, data=[139, 1, 0] + [0] * 16
    )
    raw = json.dumps(value, separators=(",", ":")).encode()
    assert len(raw) <= 512 and PlanningReadback.parse_for(q, raw).arg == 139
    with pytest.raises(ValueError, match="512"):
        PlanningReadback.parse_for(q, b" " * 513)
    with pytest.raises(ValueError, match="duplicate"):
        PlanningReadback.parse_for(q, raw[:-1] + b',"arg":139}')
    with pytest.raises(ValueError, match="identity"):
        PlanningReadback.parse_for(q, json.dumps(value | dict(arg=140)).encode())
    with pytest.raises(ValueError, match="shape"):
        PlanningReadback.parse_for(q, json.dumps(value | dict(data=[1])).encode())


def test_native_correspondence_cannot_be_created_by_controlled_labels():
    from app.simulation.openttd.freight_runtime_planning import NativeSaveCorrespondence

    with pytest.raises(ValueError, match="issuer"):
        NativeSaveCorrespondence(
            object(),
            world=None,
            original_digest="a" * 64,
            final_digest="b" * 64,
            configuration_digest="c" * 64,
        )


def test_native_save_label_does_not_upgrade_controlled_observation(tmp_path):
    from dataclasses import replace
    from types import SimpleNamespace

    from app.simulation.openttd.freight_runtime_planning import native_correspondence
    from app.simulation.openttd.prepared_source_correspondence import SourceTrust

    world = materialize(tmp_path)
    _, prepared, _ = admit(tmp_path, world=world)
    source = prepared.correspondence
    labelled = replace(
        source,
        links=source.links.model_copy(update={"evidence_kind": "owned-native-save-snapshots"}),
    )
    assert labelled.trust is SourceTrust.CONTROLLED_FIXTURE
    with pytest.raises(PlanningFactError, match="unproven"):
        labelled.require_real_executable_source()
    with pytest.raises(ValueError, match="owned continuous"):
        native_correspondence(
            SimpleNamespace(process=None, session=None),
            None,
            world,
            source.manifest,
            source.links.original_save_digest,
            "b" * 64,
        )


def test_native_planning_fact_handler_reports_settings_and_tile_values():
    import json

    from app.simulation.openttd.freight_runtime_planning import PlanningRead, PlanningReadback
    from app.simulation.openttd.proof import freight_delivery as proof
    from tests.test_freight_delivery import delivery_vm

    vm = delivery_vm()
    staged = proof.staged_package(True, True)
    vm.execute(staged["delivery.nut"].decode().replace('require("vehicle.nut");', ""))
    vm.execute(staged["demo-world.nut"].decode().replace('require("delivery.nut");', ""))
    vm.execute(
        staged["main.nut"]
        .decode()
        .replace('require("demo-world.nut");', "")
        .replace('require("qualification.nut");', "")
    )
    vm.execute("""
        class PlannerObserver {function ValidRequestID(s){return true;}}
        ::GSGameSettings <- class {static function GetValue(key){
            return key=="station.modified_catchment"?1:0;}}
        GSRoad.BT_ROAD <- 0;GSRoad.BT_TRUCK_STOP <- 1;GSRoad.BT_DEPOT <- 2;
        GSRoad.GetBuildCost <- function(t,k){return k==0?20:100;};
        GSRoad.GetMaxSpeed <- function(t){return 0;};
        ::bridge=PlannerFreightProof();bridge.observer=PlannerObserver();
    """)
    from typing import Literal

    kinds: tuple[Literal["settings", "tile"], ...] = ("settings", "tile")
    for index, kind in enumerate(kinds):
        request = PlanningRead(
            request_id=f"planning-{index}", kind=kind, arg=587, src=7, dst=8, cargo=3
        )
        vm.execute("bridge.Handle(" + request.to_bytes().decode() + ");")
        table = vm.get_roottable()["replies"][index]
        data = {
            str(k): str(table[k])
            if str(k) in ("kind", "type", "request_id")
            else [int(v) for v in table[k]]
            if str(k) == "data"
            else int(table[k])
            for k in table.keys()
        }
        raw = json.dumps(data, separators=(",", ":")).encode()
        response = PlanningReadback.parse_for(request, raw)
        if kind == "settings":
            assert response.data == (1, 0, 0, 3, 0, 20, 100, 100)
        else:
            assert response.data[:4] == (587, 1, 0, 1)
            assert response.data[14:] == (-1, 1, 8, 1, 0)
    assert int(vm.get_roottable()["actual"]) == 0


def test_planner_preparation_is_sealed_and_does_not_launch(tmp_path, monkeypatch):
    import json

    from app.simulation.openttd.proof import freight_delivery as proof

    def forbidden(*args, **kwargs):
        pytest.fail("preparation launched or connected")

    monkeypatch.setattr(proof.PlannerBackend, "launch", forbidden)
    monkeypatch.setattr(proof.PlannerDeliverySession, "connect_secure", forbidden)
    p = proof.prepare(
        tmp_path / "openttd-15.3-first-freight-delivery-attempt1", demo=True, planner=True
    )
    try:
        proof.preflight(p)
        metadata = json.loads((p.directory / "PRELAUNCH.json").read_bytes())
        assert metadata["planner"] is True and metadata["delivery_batch_limit"] == 20
        assert metadata["budgets"] == proof.PLANNER_BUDGETS
        assert not (p.directory / "CLAIM.json").exists()
    finally:
        p.spec.workspace.close()


@pytest.mark.parametrize("value", [0, -1, 65536])
def test_batch_policy_rejects_invalid_limits(value):
    from datetime import date

    from app.planning.p08_adapter import MonthlyBatchPolicy

    with pytest.raises(ValueError):
        MonthlyBatchPolicy(start_date=date(1950, 1, 1), delivery_batch_limit=value)


def test_existing_pipeline_compiles_single_vehicle_and_preserves_controlled_trust(tmp_path):
    recipe = RECIPE.model_copy(update={"quantity": 20})
    world = materialize(tmp_path, recipe)
    _, _, road = admit(tmp_path, world=world)
    assert isinstance(road, ControlledRoadScenario)
    result = optimize_candidate_network(road.scenario)
    service = compile_freight_service(road, result.plan)
    assert (
        service.source,
        service.destination,
        service.cargo,
        service.engine,
        service.capacity,
    ) == (11, 16, 3, 23, 30)
    assert len(service.execution_plan_digest) == 64
    with pytest.raises(PlanningFactError, match="correspondence unproven"):
        service.require_real_executable_source()


def test_multiple_vehicle_p05_result_is_not_silently_reduced_to_one(tmp_path):
    world = materialize(tmp_path)
    _, _, road = admit(tmp_path, world=world)
    assert isinstance(road, ControlledRoadScenario)
    result = optimize_candidate_network(road.scenario)
    assert result.plan.fleet.groups[0].count == 4
    with pytest.raises(ValueError, match="single-vehicle"):
        compile_freight_service(road, result.plan)


def test_packaged_gsmap_calls_match_openttd_15_3_contract():
    """Check shipped Squirrel names against the retained upstream API, without mocks."""
    import re
    from pathlib import Path

    from app.simulation.openttd.proof.freight_delivery import staged_package

    header = (Path(__file__).parent / "reference/map_api_15_3/script_map.hpp").read_text()
    methods = set(re.findall(r"static \w+ (\w+)\(", header))
    assert {"DistanceManhattan", "IsValidTile"} <= methods
    for name, content in staged_package(True, True).items():
        if name.endswith(".nut"):
            calls = set(re.findall(r"GSMap\.(\w+)\(", content.decode()))
            assert calls <= methods, (name, calls - methods)


def test_attempt6_recorded_route_requires_origin_entrance_bit():
    import json
    from pathlib import Path

    from app.simulation.openttd.proof.freight_delivery import staged_package
    from tests.test_freight_delivery import delivery_vm

    recorded = json.loads(
        (Path(__file__).parent / "reference/freight_attempt6_route.json").read_text()
    )
    selection = recorded["selection"]
    vm = delivery_vm()
    staged = staged_package(True, True)
    for name, dependency in (
        ("delivery.nut", "vehicle.nut"),
        ("demo-world.nut", "delivery.nut"),
        ("main.nut", "demo-world.nut"),
    ):
        vm.execute(
            staged[name]
            .decode()
            .replace(f'require("{dependency}");', "")
            .replace('require("qualification.nut");', "")
        )
    vm.execute("""
        GSRoad.HasRoadType <- function(t,rt){
            return rt==0&&(t in ::roads||t in ::stops||t in ::depots);};
        ::bridge=PlannerFreightProof();
    """)
    vm.execute("bridge.planner_selected=" + json.dumps(selection) + ";")
    vm.execute("bridge.choice={a=bridge.planner_selected.a};")
    # Decode the retained 15.3 map fields into the VM's explicit directional bits.
    for row in recorded["tiles"]:
        assert row["m1"] & 31 == 0
        assert row["m4"] & 63 == 0
        tile = row["tile"]
        if row["type"] == 2 and row["m5"] < 64:
            bits = [offset for bit, offset in enumerate((-64, 1, 64, -1)) if row["m5"] & (1 << bit)]
            vm.execute(f"::roads[{tile}]<-true;::roadbits[{tile}]<-{{}};")
            for offset in bits:
                vm.execute(f"::roadbits[{tile}][{offset}]<-true;")
        else:
            front = tile + (-1, 64, 1, -64)[row["m5"] & 3]
            kind = "stops" if row["type"] == 5 else "depots"
            vm.execute(f"::{kind}[{tile}]<-{front};")
    path = selection["path"]
    edges = list(zip(path, path[1:], strict=False)) + [(1300, 1236), (1764, 1700), (1172, 1236)]
    failed = []
    for a, b in edges:
        vm.execute(
            f"::forward<-GSRoad.AreRoadTilesConnected({a},{b});"
            f"::backward<-GSRoad.AreRoadTilesConnected({b},{a});"
        )
        if not vm.get_roottable()["forward"] or not vm.get_roottable()["backward"]:
            failed.append((a, b))
    assert failed == [(1300, 1236)]
    vm.execute('if(bridge.Route(bridge.choice.a))throw "disconnected route admitted";')
    vm.execute("::roads={};::roadbits={};::stops={};::depots={};")
    for stage in range(6):
        vm.execute(f'if(!bridge.Execute({stage}))throw "construction failed";')
    vm.execute('if(!bridge.Route(bridge.choice.a))throw "origin entrance remains disconnected";')
    vm.execute("""
        ::route_logs<-[];GSLog.Info<-function(s){::route_logs.append(s);};
        bridge.dstage=6;bridge.Route(bridge.choice.a);bridge.Route(bridge.choice.a);
        if(::route_logs.len()!=27)throw "unbounded or incomplete route diagnostics";
        GSRoad.HasRoadType<-function(t,rt){return t!=1236;};
        if(bridge.Route(bridge.choice.a))throw "wrong road type admitted";
        GSRoad.HasRoadType<-function(t,rt){return true;};
        GSTile.GetOwner<-function(t){return t==1236?1:0;};
        if(bridge.Route(bridge.choice.a))throw "foreign road admitted";
    """)


def test_attempt7_quote_accounts_for_the_built_bay_and_retains_failed_state_change():
    import json
    from pathlib import Path

    from app.simulation.openttd.proof.freight_delivery import staged_package
    from tests.test_freight_delivery import delivery_vm

    recorded = json.loads(
        (Path(__file__).parent / "reference/freight_attempt7_construction.json").read_text()
    )
    assert recorded["funds_before"] - recorded["funds_after"] == recorded["stage_cost"] == 378
    assert recorded["tiles"][0]["MAP5"] == 15
    assert recorded["tiles"][1]["MAPT"] >> 4 == 5
    assert recorded["road_bit_cost"] == 71
    vm = delivery_vm()
    staged = staged_package(True, True)
    for name, dependency in (
        ("delivery.nut", "vehicle.nut"),
        ("demo-world.nut", "delivery.nut"),
        ("main.nut", "demo-world.nut"),
    ):
        vm.execute(
            staged[name]
            .decode()
            .replace(f'require("{dependency}");', "")
            .replace('require("qualification.nut");', "")
        )
    vm.execute("""
        ::bridge=PlannerFreightProof();::command_logs<-[];
        GSLog.Info<-function(s){::command_logs.append(s);};
        bridge.planner_selected={a=[0,1,1,123,1300,1236,1764,1700,1172,1236],
            path=[1236,1237],depot_front=1236};bridge.choice={a=bridge.planner_selected.a};
        GSRoad.GetBuildCost<-function(t,k){return 71;};
        GSTile.DemolishTile<-function(t){
            if(!(::account in ::tests))throw "native quote mutated world";::cost=15;return true;};
        GSRoad.BuildRoadStation<-function(t,f,k,s){::cost=307;
            if(::account in ::tests)return true;::funds-=307;::stops[t]<-f;return true;};
        GSRoad.BuildRoad<-function(a,b){
            ::cost=(GSRoad.HasBit(a,b)?0:71)+(GSRoad.HasBit(b,a)?0:71);
            if(::account in ::tests){if(!(b in ::stops))::cost+=15;return ::cost>0;}
            ::funds-=::cost;::roadbits[a][b-a]<-true;return true;};
        ::roads[1236]<-true;::roadbits[1236]<-{[-64]=true,[1]=true,[-1]=true};
        ::quote<-bridge.Quote(3);
        if(!::quote[0]||::quote[1]!=378)throw "future bay bit overquoted";
        ::accounting<-GSAccounting();
        if(!bridge.Execute(3)||::accounting.GetCosts()!=378)
            throw "quote differs from executed spending";
        if(!bridge.Linked(1300,1236))throw "recorded entrance not reproduced";
        ::roadbits[1236].rawdelete(64);
        GSRoad.BuildRoad<-function(a,b){::funds-=71;::roadbits[a][b-a]<-true;return false;};
        if(bridge.CheckedRoad(1236,1300,false))throw "failed command silently accepted";
        if(::command_logs.top().find("classification=FAILED_STATE_CHANGED")==null)
            throw "failed command not retained";
        if(!bridge.CheckedRoad(1236,1300,false))throw "already satisfied entrance rejected";
        if(::command_logs.top().find("classification=ALREADY_SATISFIED")==null)
            throw "satisfied state not distinguished";
    """)


@pytest.mark.parametrize("tamper", [None, "failed", "spending", "missing"])
def test_construction_command_receipt_replay_rejects_failure_or_missing_evidence(tmp_path, tamper):
    from types import SimpleNamespace

    from app.simulation.openttd.proof.freight_delivery import command_readback_evidence

    plan = SimpleNamespace(digest="a" * 64)
    lines = []
    records = {}
    for i in range(10):
        cost = 100 if i < 6 else (5000 if i == 6 else 0)
        state = [0] * 30
        state[23] = cost
        records[f"build-{i}"] = SimpleNamespace(s=state)
        lines.append(
            f"FREIGHT_CONSTRUCTION_STAGE plan={plan.digest} stage={i} result=1 "
            f"quoted={cost} cost={cost} spent={cost}"
        )
        if i < 6:
            lines.append(
                f"FREIGHT_CONSTRUCTION_ROAD plan={plan.digest} stage={i} a=1236 b=1300 "
                "full=0 before=0 result=1 error=0 after=1 spent=100 "
                "classification=COMMAND_SUCCEEDED"
            )
    text = "\n".join(lines)
    if tamper == "failed":
        text = text.replace(
            "classification=COMMAND_SUCCEEDED", "classification=FAILED_STATE_CHANGED", 1
        )
    elif tamper == "spending":
        text = text.replace("spent=100 classification", "spent=99 classification", 1)
    elif tamper == "missing":
        text = "\n".join(lines[:-1])
    log = tmp_path / "stderr.log"
    log.write_text(text)
    if tamper:
        with pytest.raises(ValueError):
            command_readback_evidence(log, plan, records)
    else:
        replay = command_readback_evidence(log, plan, records)
        assert len(replay["construction_command_readbacks"]) == 6
        assert len(replay["construction_stage_readbacks"]) == 10
