"""Controlled checks for the existing executor's two-service session extension."""

import json

import pytest
from test_freight_delivery import delivery_vm
from test_freight_network import packages  # noqa: F401, F811

from app.planning.optimizer import optimize_candidate_network
from app.planning.p08_adapter import adapt_planning_facts
from app.planning.p08_network import generate_freight_network
from app.simulation.openttd.freight_delivery import (
    DeliveryReadback,
    DeliveryRequest,
    admit,
    verify_delivery,
)
from app.simulation.openttd.freight_native_network import stage_assets
from app.simulation.openttd.freight_planning import compile_freight_network
from app.simulation.openttd.proof.freight_delivery import staged_package


def test_native_compiler_preserves_p05_identities_and_controlled_trust(packages):  # noqa: F811
    inputs = tuple(
        adapt_planning_facts(p.admitted, p.policy.model_copy(update={"delivery_batch_limit": 30}))
        for p in packages
    )
    network = generate_freight_network(inputs, max_vehicles=2)
    plan = optimize_candidate_network(network.scenario).plan
    services = compile_freight_network(network, plan)
    assert len(services) == 2
    assert [s.destination for _, s in services] == [17, 30]
    assert all(s.capacity == 30 for _, s in services)
    assert tuple(i for i, _ in services) == tuple(r.route_id for r in plan.routes)
    for route_id, service in services:
        assert set(stage_assets(plan, route_id)) == set(range(6))
        with pytest.raises(ValueError, match="unproven"):
            service.selection_request()


def network_vm():
    vm = delivery_vm()
    staged = staged_package(True, True, True)
    for name in ("delivery.nut", "demo-world.nut", "network-parent.nut", "main.nut"):
        code = staged[name].decode()
        for line in code.splitlines():
            if line.startswith("require("):
                code = code.replace(line, "")
        vm.execute(code)
    vm.execute("""
        ::vehicles <- {};
        ::GSVehicleList = class {function Count(){return ::vehicles.len();}};
        ::GSVehicle = class extends GSVehicle {
            static VS_STOPPED=1;
            static function IsValidVehicle(v){return v in ::vehicles;}
            static function GetLocation(v){local c=::vehicles[v];
                return !c.started?c.depot:(::ticks-c.start<20?c.src:c.dst);}
            static function GetState(v){local c=::vehicles[v];
                return c.stopped?1:(!c.started?2:3);}
            static function IsInDepot(v){return !::vehicles[v].started;}
            static function GetCargoLoad(v,c){local a=::vehicles[v];
                return a.started&&::ticks-a.start>=5&&::ticks-a.start<25?20:0;}
            static function GetProfitThisYear(v){local c=::vehicles[v];
                return c.started&&::ticks-c.start>=25?480:0;}
            static function BuildVehicle(d,e){::cost=5000;if(::account in ::tests)return 0;
                ::funds-=5000;local v=23+::vehicles.len();
                ::vehicles[v]<-{depot=d,src=::bridge.choice.a[4],dst=::bridge.choice.a[6],
                    started=false,stopped=false,start=0};return v;}
            static function StartStopVehicle(v){::cost=0;if(::account in ::tests)return true;
                local c=::vehicles[v];if(c.started){c.stopped=true;}else{
                    c.started=true;c.start=::ticks;::running=true;}return true;}
        };
        ::orders <- {};
        ::GSOrder = class extends GSOrder {
            static function GetOrderCount(v){return v in ::orders?::orders[v].len():0;}
            static function GetOrderDestination(v,i){return ::orders[v][i][0];}
            static function GetOrderFlags(v,i){return ::orders[v][i][1];}
            static function IsGotoStationOrder(v,i){return i<GetOrderCount(v);}
            static function AppendOrder(v,t,f){::cost=0;if(::account in ::tests)return true;
                if(!(v in ::orders))::orders[v]<-[];::orders[v].append([t,f]);return true;}
        };
        ::GSCompany = class extends GSCompany {
            static function GetQuarterlyCargoDelivered(c,q){local n=0;
                foreach(v,a in ::vehicles)if(a.started&&::ticks-a.start>=25)n+=20;return n;}
            static function GetQuarterlyIncome(c,q){return GetQuarterlyCargoDelivered(c,q)*25;}
        };
        ::GSIndustry = class extends GSIndustry {
            static function IsValidIndustry(i){return i==7||i==8||i==9||i==10;}
            static function GetIndustryID(t){return t==650?7:(t==1300?8:
                (t==2186?9:(t==2836?10:-1)));}
            static function GetLocation(i){return i==7?650:(i==8?1300:(i==9?2186:2836));}
            static function GetIndustryType(i){return i==7||i==9?3:4;}
            static function GetLastMonthProduction(i,c){return (i==7||i==9)&&c==3?100:0;}
            static function IsCargoAccepted(i,c){return (i==8||i==10)&&c==3?1:0;}
            static function GetCargoLastAcceptedDate(i,c){return GSDate.GetCurrentDate();}
        };
        ::GSCargoMonitor = class {
            static function GetIndustryPickupAmount(company,cargo,industry,keep){return keep?0:20;}
            static function GetIndustryDeliveryAmount(company,cargo,industry,keep){
                return keep?0:20;}
        };
        ::bridge=NetworkFreightProof();
    """)
    return vm


def test_two_services_deliver_and_stop_in_one_executor_session():
    from app.simulation.openttd.freight_planning import PlanningSelectionRequest

    vm = network_vm()

    def exchange(request):
        vm.execute("::bridge.Handle(" + request.to_bytes().decode() + ");")
        replies = vm.get_roottable()["replies"]
        reply = replies[len(replies) - 1]
        value = {}
        for key in reply.keys():
            k = str(key)
            v = reply[k]
            value[k] = (
                str(v)
                if k in ("op", "request_id", "plan", "status")
                else [int(v[i]) for i in range(len(v))]
                if k in ("a", "f", "s", "e")
                else int(v)
            )
        raw = json.dumps(value).encode()
        return DeliveryReadback.parse_for(getattr(request, "admission_request", request), raw)

    selections = []
    for n in range(2):
        shift = n * 1536
        a = (
            7 + 2 * n,
            8 + 2 * n,
            3,
            42,
            585 + shift,
            586 + shift,
            1235 + shift,
            1171 + shift,
            522 + shift,
            595 + shift,
        )
        path = tuple(range(586 + shift, 596 + shift)) + tuple(range(659 + shift, 1172 + shift, 64))
        request = PlanningSelectionRequest(
            request_id=f"select-{n}", plan="a" * 64, a=a, path=path, depot_front=586 + shift
        )
        read = exchange(request)
        assert read.status == "READY"
        selections.append(admit(read, "a" * 64, "b" * 64, None, selection_digest="a" * 64))
    receipts = []
    for n, plan in enumerate(selections):

        def query(op, name, arg=0):
            return exchange(DeliveryRequest(op=op, request_id=name, arg=arg, plan=plan.digest))

        assert query("read", f"activate-{n}", n).status == "READ"
        baseline = None
        for i in range(10):
            assert query("build", f"s{n}-build-{i}", i).status == "BUILT"
            read = query("read", f"s{n}-read-{i}", i)
            if i == 8:
                baseline = read
        observations = [query("observe", f"s{n}-observe-{i}", i) for i in range(4)]
        final = query("finish", f"s{n}-finish")
        receipts.append(verify_delivery(plan, baseline, observations, final))
        assert query("finish", f"s{n}-park", 1).status == "PARKED"
        assert query("read", f"s{n}-park-read").s[9] == 1
    assert [r["delivered"] for r in receipts] == [20, 20]
    assert [r["payment_income"] for r in receipts] == [500, 500]
    assert [r["vehicle"] for r in receipts] == [23, 24]
