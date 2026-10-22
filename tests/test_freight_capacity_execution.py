"""Controlled GameScript execution and independent receipt replay; no native use."""

import json
from pathlib import Path

import pytest
from squirrel import SQVM

from app.simulation.openttd.freight_capacity_execution import (
    capacity_request,
    decode_capacity_receipt,
    validate_capacity_replay,
)


def capacity_vm(service=1, *, failure=-1):
    vm = SQVM()
    vm.execute("""
        ::testmode <- false; ::funds <- 10000; ::cost <- 0; ::norders <- 0;
        ::created <- false; ::started <- false; ::failstage <- -1; ::replies <- [];
        class NetworkFreightProof {
            services=null;
            function PrepareDemo() { throw "UNEXPECTED_CAPACITY_WORLD_PREPARATION"; }
            function Store() {}
            function GetTick() { return 10; }
            function ExpectedVehicleCount() { return 3; }
        }
        class GSCompanyMode { constructor(c) {} static function IsValid() { return true; } }
        class GSGame { static function IsPaused() { return true; } }
        class GSRoad { static function SetCurrentRoadType(t) {} }
        class GSCompany {
            static function GetBankBalance(c) { return ::funds; }
            static function GetAutoRenewStatus(c) { return false; }
        }
        class GSVehicleList { function Count() { return ::created?4:3; } }
        class GSAccounting {
            constructor() { ::cost=0;::testmode=false; }
            function GetCosts() { return ::cost; } }
        class GSTestMode { constructor() { ::testmode=true; } }
        class GSVehicle {
            static VS_RUNNING=0; static VS_AT_STATION=3;
            static function IsValidVehicle(v) { return v>=1&&v<=3||v==4&&::created; }
            static function GetOwner(v) { return 0; }
            static function GetEngineType(v) { return 5; }
            static function GetCapacity(v,c) { return 20; }
            static function GetState(v) { return v==4&&!::started?2:0; }
            static function IsInDepot(v) { return !::started; }
            static function GetLocation(v) { return 30; }
            static function BuildVehicle(d,e) {
                ::cost=4429;if(::testmode)return 0;
                ::funds-=4429;::created=true;return 4;
            }
            static function StartStopVehicle(v) {
                if(::testmode)return true;::started=true;return true;
            }
        }
        class GSOrder {
            static OF_FULL_LOAD=64; static OF_NO_LOAD=128;
            static function GetOrderCount(v) { return v==4?::norders:2; }
            static function GetOrderDestination(v,n) { return n==0?10:20; }
            static function GetOrderFlags(v,n) { return n==0?64:128; }
            static function IsGotoStationOrder(v,n) { return true; }
            static function AppendOrder(v,t,f) {
                if(::testmode)return true;
                if(::failstage==::norders+1)return false;
                ::norders++;return true;
            }
        }
        class GSDate { static function GetCurrentDate() { return 100; } }
        class GSAdmin { static function Send(r) { ::replies.append(r); return true; } }
    """)
    vm.execute(
        Path("app/simulation/openttd/freight_delivery_package/continuous.nut")
        .read_text()
        .replace('require("continuous-parent.nut");', "")
    )
    vm.execute(f'''
        ::failstage={failure};::b <- ContinuousFreightProof();
        b.services=[];for(local i=0;i<3;i++)b.services.append({{
            dstage=10,dfailed=false,dvehicle=i+1,dplan="{"a" * 64}",
            choice={{a=[0,1,2,5,10,0,20,0,30]}} }});
        ::q <- {{protocol=1,type="capacity-add",request_id="add-1",
            service={service},max_cost=5000}};
        b.Handle(q);
    ''')
    return vm


def plain(value):
    if hasattr(value, "keys"):
        return {str(k): plain(value[k]) for k in value.keys()}
    if type(value).__name__ == "SQArray":
        return [plain(value[i]) for i in range(len(value))]
    return value


def decode(vm, index, *, read=False, service=1):
    raw = json.dumps(plain(vm.get_roottable()["replies"][index])).encode()
    return decode_capacity_receipt(
        raw, capacity_request("read-1" if read else "add-1", service, 5000, read=read)
    )


def replay(command, readback, service=1):
    return validate_capacity_replay(
        command,
        readback,
        plan="a" * 64,
        service=service,
        original_vehicle=service + 1,
        engine=5,
        cargo=2,
        capacity=20,
        source=10,
        destination=20,
        full_load_flag=64,
        no_load_flag=128,
        max_cost=5000,
    )


@pytest.mark.parametrize("service", [0, 1, 2])
def test_actual_producer_fourth_vehicle_and_independent_readback(service):
    vm = capacity_vm(service)
    command = decode(vm, 0, service=service)
    vm.execute('q.type="capacity-read";q.request_id="read-1";b.Handle(q);')
    readback = decode(vm, 1, read=True, service=service)
    assert replay(command, readback, service) == {
        "service": service,
        "vehicle": 4,
        "purchase_capex": 4429,
    }
    assert vm.get_roottable()["b"].ExpectedVehicleCount() == 4


def test_partial_order_mutation_retains_vehicle_and_refuses_retry():
    vm = capacity_vm(failure=2)
    raw = plain(vm.get_roottable()["replies"][0])
    assert raw["status"] == "partial"
    assert raw["vehicle"] == 4 and raw["purchase_capex"] == 4429
    assert len(raw["orders"]) == 1
    with pytest.raises(ValueError, match="partial capacity"):
        decode(vm, 0)
    with pytest.raises(Exception, match="CAPACITY_BOUNDARY_INVALID"):
        vm.execute("b.Handle(q);")


def test_receipt_correlation_and_complete_commands():
    vm = capacity_vm()
    command = decode(vm, 0)
    vm.execute('q.type="capacity-read";q.request_id="read-1";b.Handle(q);')
    readback = decode(vm, 1, read=True)
    with pytest.raises(ValueError, match="completeness"):
        replay(command.model_copy(update={"commands": command.commands[:3]}), readback)
    with pytest.raises(ValueError, match="identity"):
        replay(command, readback.model_copy(update={"service": 2}))


def test_exchange_request_receipt_adapter():
    from app.simulation.openttd.freight_capacity_execution import CapacityReceipt, CapacityRequest

    vm = capacity_vm()
    raw = json.dumps(plain(vm.get_roottable()["replies"][0])).encode()
    request = CapacityRequest("add-1", 1, 5000)
    assert request.type == "capacity-add"
    assert CapacityReceipt.parse_for(request, raw).vehicle == 4
    with pytest.raises(ValueError, match="duplicate capacity key"):
        decode_capacity_receipt(raw[:-1] + b',"service":1}', request.to_bytes())


def test_independent_readback_does_not_accept_stopped_vehicle():
    vm = capacity_vm()
    command = decode(vm, 0)
    vm.execute('::started=false;q.type="capacity-read";q.request_id="read-1";b.Handle(q);')
    readback = decode(vm, 1, read=True)
    with pytest.raises(ValueError, match="identity"):
        replay(command, readback)


def test_independent_readback_detects_changed_orders():
    vm = capacity_vm()
    command = decode(vm, 0)
    vm.execute('::norders=1;q.type="capacity-read";q.request_id="read-1";b.Handle(q);')
    readback = decode(vm, 1, read=True)
    with pytest.raises(ValueError, match="identity"):
        replay(command, readback)


def test_original_three_vehicle_count_without_intervention():
    vm = capacity_vm()
    vm.execute("b.capacity_vehicle=-1;")
    assert vm.get_roottable()["b"].ExpectedVehicleCount() == 3
