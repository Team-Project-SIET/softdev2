"""Controlled packaged callbacks; never native save/reload qualification."""

import json

import pytest
from test_freight_capacity_execution import plain
from test_native_freight_network import network_vm

from app.simulation.openttd.proof.freight_delivery import staged_package


def persistence_vm():
    vm = network_vm(3)
    package = staged_package(True, True, True, "high-budget-500k", 3, 5)
    for name in (
        "funding.nut",
        "delivery.nut",
        "demo-world.nut",
        "network-parent.nut",
        "continuous-parent.nut",
        "main.nut",
    ):
        vm.execute(
            "\n".join(
                line
                for line in package[name].decode().splitlines()
                if not line.startswith("require(")
            )
        )
    vm.execute("""
        ::GSCompany=class extends GSCompany {
            static function GetAutoRenewStatus(c){return false;}
        };
        ::source <- ContinuousFreightProof();
        source.capital_funding=ScenarioCapitalFunding();
        source.capital_funding.completed=true;source.capital_funding.attempted=true;
        source.capital_funding.autorenew_set=true;
        source.services=[];
        for(local i=0;i<3;i++) source.services.append({
            choice={a=[i,i+3,0,5,10+i,20+i,30+i,40+i,50+i,60+i]},
            planner_selected={route=i},dplan="plan"+i,dstage=10,dvehicle=i+1,
            dfailed=false,dstations=[i,i+3],monitors=false,monitor_pickup=0,
            monitor_delivery=0,period=null,closed=null,baseline=null,obs_stage=0,route_logged=true});
        source.LoadService(1);source.dplan="active-plan";
    """)
    return vm


def test_actual_packaged_callbacks_preserve_services_and_active_state():
    vm = persistence_vm()
    vm.execute("""
        ::saved <- source.Save();
        ::target <- ContinuousFreightProof();target.Load(1,saved);
        if(target.services==null||target.services.len()!=3)throw "SERVICE_BINDINGS_LOST";
        if(target.active!=1||target.dplan!="active-plan"||target.dvehicle!=2)
            throw "ACTIVE_BINDING_LOST";
        target.PrepareDemo();
        if(!target.capital_funding.resumed)throw "FUNDING_NOT_RESUMED";
    """)


def test_partial_save_remains_available_but_cannot_resume():
    vm = persistence_vm()
    vm.execute("source.dstage=9;::saved <- source.Save();::target <- ContinuousFreightProof();")
    with pytest.raises(Exception, match="CANONICAL_SAVE_UNSUPPORTED"):
        vm.execute("target.Load(1,saved);")


def test_frozen_save_roundtrip_to_independent_vm():
    source = persistence_vm()
    source.execute("::saved <- source.Save();source.services[0].dvehicle=999;")
    frozen = json.dumps(plain(source.get_roottable()["saved"]))
    target = persistence_vm()
    target.execute("::target <- ContinuousFreightProof();target.Load(1," + frozen + ");")
    target.execute(
        'if(target.services[0].dvehicle!=1||target.dvehicle!=2)throw "SERIALIZED_BINDING_LOST";'
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "delete saved.fleet.services[0].dvehicle;",
        "saved.fleet.services[0].dvehicle=2;",
        "saved.fleet.state.active=4;",
        "saved.fleet.services[0].choice.a=null;",
    ],
)
def test_malformed_bindings_rejected(mutation):
    vm = persistence_vm()
    vm.execute("::saved <- source.Save();" + mutation)
    with pytest.raises(Exception, match="CANONICAL_SAVE_INVALID"):
        vm.execute("::target <- ContinuousFreightProof();target.Load(1,saved);")


@pytest.mark.parametrize("mutation", ["source.cbegun=true;", "source.capacity_attempted=true;"])
def test_operated_save_is_diagnostic_only(mutation):
    vm = persistence_vm()
    vm.execute(mutation + "::saved <- source.Save();")
    with pytest.raises(Exception, match="CANONICAL_SAVE_UNSUPPORTED"):
        vm.execute("::target <- ContinuousFreightProof();target.Load(1,saved);")


def test_continuous_without_funding_preserves_diagnostic_save():
    vm = network_vm(3)
    package = staged_package(True, True, True, network_service_limit=3, continuous_years=5)
    for name in ("continuous-parent.nut", "main.nut"):
        vm.execute(
            "\n".join(
                line
                for line in package[name].decode().splitlines()
                if not line.startswith("require(")
            )
        )
    vm.execute("::source <- ContinuousFreightProof();::saved <- source.Save();")
    with pytest.raises(Exception, match="CANONICAL_SAVE_UNSUPPORTED"):
        vm.execute("::target <- ContinuousFreightProof();target.Load(1,saved);")
