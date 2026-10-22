"""Controlled protocol coverage; never starts a native process."""

import asyncio
import json
from pathlib import Path

import pytest

from app.simulation.openttd.freight_canonical_dispatch import (
    BoundaryReceipt,
    BoundaryRequest,
    require_stable_boundary,
)


def receipt(**changes):
    data = dict(
        protocol=1,
        type="canonical-ready-result",
        request_id="canonical-ready",
        service=-1,
        status="ok",
        tick=10,
        economy_date=30000,
        paused=True,
        command_pause_level=2,
        restored=True,
        originals=[[i, i + 1, 100 + i, 0, 0, 2] for i in range(3)],
        extra=None,
        cash=400000,
        loan=0,
    )
    data.update(changes)
    return BoundaryReceipt.parse_for(BoundaryRequest("canonical-ready"), json.dumps(data).encode())


def test_boundary_correlation_and_completeness():
    assert receipt().originals[0] == (0, 1, 100, 0, 0, 2)
    for change in (dict(request_id="other"), dict(paused=False), dict(originals=[])):
        with pytest.raises(ValueError):
            receipt(**change)


def test_paused_heartbeat_requires_ticks_without_world_time():
    require_stable_boundary(receipt(), receipt(tick=11))
    for change in (dict(tick=10), dict(economy_date=30001), dict(cash=399999), dict(loan=1)):
        with pytest.raises(ValueError):
            require_stable_boundary(
                receipt(), receipt(tick=11, **change) if "tick" not in change else receipt(**change)
            )


def test_dispatch_allows_only_original_start_flags():
    rows = [[i, i + 1, 100 + i, 0, 0, 0] for i in range(3)]
    require_stable_boundary(receipt(), receipt(tick=11, originals=rows), started=True)
    with pytest.raises(ValueError):
        require_stable_boundary(receipt(), receipt(tick=11, originals=rows))
    rows[1][2] += 1
    with pytest.raises(ValueError):
        require_stable_boundary(receipt(), receipt(tick=11, originals=rows), started=True)


@pytest.mark.parametrize("kind,service", [("canonical-seal", 0), ("canonical-arm", -1)])
def test_boundary_request(kind, service):
    assert json.loads(BoundaryRequest("a", kind, service).to_bytes())["service"] == service
    with pytest.raises(ValueError):
        BoundaryRequest("bad/path", kind, service).to_bytes()


def test_native_stopped_depot_predicate_and_no_start_acquisition():
    source = Path("app/simulation/openttd/freight_delivery_package/canonical.nut").read_text()
    # Native 15.3 GetState returns VS_IN_DEPOT before VS_STOPPED: the predicate
    # has to test IsStoppedInDepot rather than assuming a state enum value.
    others = source.split("function OthersStopped()", 1)[1].split("function Execute", 1)[0]
    assert "IsStoppedInDepot" in others
    assert "VS_STOPPED" not in source
    execute = source.split("function Execute(i)", 1)[1].split("function CanonicalOriginals", 1)[0]
    assert 'if(i==9)throw "CANONICAL_START_FORBIDDEN"' in execute
    seal = source.split('if(q.type=="canonical-seal")', 1)[1].split("} else {", 1)[0]
    assert "dstage=10;Store()" in seal
    assert "StartStopVehicle" not in seal


def canonical_vm():
    from test_freight_canonical_persistence import persistence_vm

    vm = persistence_vm()
    vm.execute(
        "\n".join(
            line
            for line in Path("app/simulation/openttd/freight_delivery_package/canonical.nut")
            .read_text()
            .splitlines()
            if not line.startswith("require(")
        )
    )
    vm.execute("""
        ::paused <- true;::policy <- 2;::started_ids <- {};::starts <- 0;
        ::GSGame=class { static function IsPaused(){return ::paused;} };
        ::GSGameSettings <- class { static function GetValue(k){return ::policy;} };
        ::GSCompany=class extends GSCompany {static function GetLoanAmount(){return 0;}};
        ::GSVehicleList=class {function Count(){return 3;}};
        ::GSVehicle=class extends GSVehicle {
            static VS_RUNNING=0;static VS_AT_STATION=3;
            static function IsValidVehicle(v){return v>=1&&v<=3;}
            static function GetOwner(v){return 0;}
            static function GetEngineType(v){return 5;}
            static function GetCapacity(v,c){return 20;}
            static function GetCargoLoad(v,c){return 0;}
            static function GetCurrentSpeed(v){return 0;}
            static function GetLocation(v){return 49+v;}
            static function IsInDepot(v){return true;}
            static function IsStoppedInDepot(v){return !(v in ::started_ids);}
            static function GetState(v){return IsStoppedInDepot(v)?2:0;}
            static function StartStopVehicle(v){::started_ids[v]<-true;::starts++;return true;}
        };
        ::GSOrder=class extends GSOrder {
            static function GetOrderCount(v){return 2;}
            static function GetOrderDestination(v,n){return (n==0?9:29)+v;}
            static function GetOrderFlags(v,n){return n==0?GSOrder.OF_FULL_LOAD:GSOrder.OF_NO_LOAD;}
            static function IsGotoStationOrder(v,n){return true;}
        };
        class ControlledCanonical extends CanonicalFreightProof {
            function Route(a){return true;}
        }
        ::bridge=ControlledCanonical();bridge.services=source.services;
        bridge.LoadService(1);bridge.restored_fleet=true;
    """)
    return vm


def test_actual_packaged_gs_uses_native_stopped_depot_semantics():
    vm = canonical_vm()
    vm.execute('bridge.Handle({protocol=1,type="canonical-ready",request_id="ready",service=-1});')
    assert vm.get_roottable()["starts"] == 0
    vm.execute('bridge.Handle({protocol=1,type="canonical-arm",request_id="arm",service=-1});')
    vm.execute('bridge.Handle({protocol=1,type="canonical-start",request_id="start",service=-1});')
    vm.execute(
        'bridge.Handle({protocol=1,type="canonical-dispatch-read",request_id="read",service=-1});'
    )
    assert vm.get_roottable()["starts"] == 3
    with pytest.raises(Exception, match="CANONICAL_START_INVALID"):
        vm.execute(
            'bridge.Handle({protocol=1,type="canonical-start",request_id="again",service=-1});'
        )


@pytest.mark.parametrize("policy", [0, 1])
def test_actual_packaged_gs_rejects_paused_purchase_restriction(policy):
    vm = canonical_vm()
    vm.execute(f"::policy={policy};")
    with pytest.raises(Exception, match="CANONICAL_PAUSED_CONSTRUCTION_UNAVAILABLE"):
        vm.execute('bridge.Handle({protocol=1,type="canonical-arm",request_id="arm",service=-1});')
    assert vm.get_roottable()["starts"] == 0


def test_actual_packaged_seal_omits_start_and_rejects_stage9():
    vm = canonical_vm()
    vm.execute("bridge.dstage=9;bridge.Store();")
    vm.execute('bridge.Handle({protocol=1,type="canonical-seal",request_id="seal",service=1});')
    assert vm.get_roottable()["bridge"].dstage == 10
    assert vm.get_roottable()["starts"] == 0
    with pytest.raises(Exception, match="CANONICAL_START_FORBIDDEN"):
        vm.execute("bridge.Execute(9);")


@pytest.mark.parametrize("arm,purchase_only", [("A", False), ("B", False), ("B", True)])
def test_actual_dispatch_orchestration(monkeypatch, tmp_path, arm, purchase_only):
    from test_freight_canonical import observation, parse
    from test_freight_capacity_execution import capacity_vm, decode

    from app.simulation.openttd.freight_canonical_dispatch import (
        dispatch_common,
        qualify_paused_purchase,
    )

    state = parse(observation()).state
    vm = capacity_vm()
    command = decode(vm, 0)
    vm.execute('q.type="capacity-read";q.request_id="read-1";b.Handle(q);')
    independent = decode(vm, 1, read=True)
    added = 460000
    rows = [
        (n, ok, quote, cost, before + added, after + added)
        for n, ok, quote, cost, before, after in command.commands
    ]
    commands = []
    snapshots = []
    started = False
    intervened = False
    tick = 100

    async def exchange(session, request, directory, *, response_type):
        nonlocal started, intervened, tick
        tick += 1
        commands.append(request.type)
        if request.type in ("capacity-add", "capacity-read"):
            intervened = True
            value = command if request.type == "capacity-add" else independent
            return value.model_copy(
                update=dict(
                    request_id=request.request_id,
                    tick=tick,
                    economy_date=state.economy_date,
                    cash_before=470000,
                    cash_after=465571,
                    commands=rows,
                )
            )
        if request.type == "canonical-start":
            started = True
        data = receipt().model_dump(mode="json")
        data.update(
            type=request.type + "-result",
            request_id=request.request_id,
            tick=tick,
            economy_date=state.economy_date,
            loan=state.loan,
            cash=state.cash - (4429 if intervened else 0),
            originals=[[i, i + 1, 30, 0, 0, 0 if started else 2] for i in range(3)],
            extra=[1, 4, 30, 0, 0, 0] if intervened else None,
        )
        return response_type.parse_for(request, json.dumps(data).encode())

    async def snapshot(binding, capex, *, started):
        snapshots.append((binding, capex, started))
        return True

    async def unpause():
        commands.append("unpause")
        data = receipt().model_dump(mode="json")
        data.update(
            type="canonical-dispatched-result",
            request_id="canonical-dispatched",
            tick=200,
            economy_date=state.economy_date,
            paused=False,
            originals=[],
        )
        return data

    monkeypatch.setattr("app.simulation.openttd.proof.freight_delivery.exchange", exchange)
    if purchase_only:
        result = asyncio.run(
            qualify_paused_purchase(
                None,
                tmp_path,
                state,
                state,
                snapshot=snapshot,
                service_plans=("a" * 64,) * 3,
            )
        )
        assert "canonical-start" not in commands and "unpause" not in commands
    else:
        result = asyncio.run(
            dispatch_common(
                None,
                tmp_path,
                state,
                state,
                arm=arm,
                snapshot=snapshot,
                unpause=unpause,
                service_plans=("a" * 64,) * 3,
            )
        )
        assert commands[-1] == "unpause"
        assert commands[-3:-1] == ["canonical-start", "canonical-dispatch-read"]
    assert result["purchase_capex"] == (4429 if arm == "B" else 0)
    assert len(snapshots) == (1 if purchase_only else 2)


def test_native_depot_state_regression_distinguishes_wrong_predicate():
    vm = canonical_vm()
    vm.execute("""
        ::wrong <- NetworkFreightProof.OthersStopped.call(bridge);
        ::correct <- bridge.OthersStopped();
    """)
    assert vm.get_roottable()["wrong"] is False
    assert vm.get_roottable()["correct"] is True


def test_actual_gs_dispatch_ack_requires_unpaused_native_world():
    from test_freight_capacity_execution import plain

    vm = canonical_vm()
    vm.execute('bridge.Handle({protocol=1,type="canonical-arm",request_id="arm",service=-1});')
    vm.execute('bridge.Handle({protocol=1,type="canonical-start",request_id="start",service=-1});')
    vm.execute(
        '::paused=false;bridge.Handle({protocol=1,type="canonical-dispatched",request_id="canonical-dispatched",service=-1});'
    )
    replies = vm.get_roottable()["replies"]
    raw = json.dumps(plain(replies[len(replies) - 1])).encode()
    ack = BoundaryReceipt.parse_for(
        BoundaryRequest("canonical-dispatched", "canonical-dispatched"), raw
    )
    assert ack.paused is False
    assert ack.originals == []
