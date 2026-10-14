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
from app.simulation.openttd.freight_native_network import aggregate_receipt, stage_assets
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


def network_vm(service_limit=2):
    vm = delivery_vm()
    staged = staged_package(True, True, True, network_service_limit=service_limit)
    for name in ("delivery.nut", "demo-world.nut", "network-parent.nut", "main.nut"):
        code = staged[name].decode()
        for line in code.splitlines():
            if line.startswith("require("):
                code = code.replace(line, "")
        # OpenTTD 15.3's Squirrel fork has no `base` keyword. Model its
        # ordinary instance lookup instead of SQVM's newer parent-call syntax.
        if name == "main.nut":
            code = code.replace("base.", 'this["base"].')
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
            static function IsValidIndustry(i){return i==7||i==8||i==9||i==10||i==11||i==12;}
            static function GetIndustryID(t){return t==650?7:(t==1300?8:
                (t==2186?9:(t==2836?10:(t==1418?11:(t==2068?12:-1)))));}
            static function GetLocation(i){return i==7?650:(i==8?1300:
                (i==9?2186:(i==10?2836:(i==11?1418:2068))));}
            static function GetIndustryType(i){return i==7||i==9||i==11?3:4;}
            static function GetLastMonthProduction(i,c){return (i==7||i==9||i==11)&&c==3?100:0;}
            static function IsCargoAccepted(i,c){return (i==8||i==10||i==12)&&c==3?1:0;}
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


@pytest.mark.parametrize("service_count", [1, 2, 3])
def test_selected_services_deliver_and_stop_in_one_executor_session(service_count):
    from app.simulation.openttd.freight_planning import PlanningSelectionRequest

    vm = network_vm(3 if service_count == 3 else 2)
    vm.execute("""
        ::construction_logs <- [];
        ::GSLog = class extends GSLog {
            static function Info(message){::construction_logs.append(message);}
        };
    """)

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
    for n in range(service_count):
        shift = (0, 1536, 768)[n]
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
    vm.execute("""
        local stages=0;local markers=0;
        foreach(message in ::construction_logs) {
            if(message.find("FREIGHT_CONSTRUCTION_STAGE ")==0)stages++;
            if(message.find("FREIGHT_GAME_TIME_CONSTRUCTION ")==0)markers++;
        }
        if(stages!=::bridge.services.len()*10)throw "ANCESTOR_STAGE_LOG_MISSING";
        if(markers!=::bridge.services.len())throw "CONSTRUCTION_TIME_MARKER_MISSING";
    """)
    assert [r["delivered"] for r in receipts] == [20] * service_count
    assert [r["payment_income"] for r in receipts] == [500] * service_count
    assert [r["vehicle"] for r in receipts] == list(range(23, 23 + service_count))


def test_one_naturally_selected_service_aggregates_delivery_and_spending(packages):  # noqa: F811
    inputs = (
        adapt_planning_facts(
            packages[0].admitted, packages[0].policy.model_copy(update={"delivery_batch_limit": 30})
        ),
    )
    network = generate_freight_network(inputs, max_vehicles=2)
    plan = optimize_candidate_network(network.scenario).plan
    services = compile_freight_network(network, plan)
    assert len(services) == 1
    receipt = dict(
        route_id=services[0][0],
        vehicle=23,
        delivered=20,
        payment_income=500,
        construction_purchase_spending=5021,
        mutation_costs=[1, 2, 3, 4, 5, 6, 5000],
    )
    aggregate = aggregate_receipt(plan, services, [receipt])
    assert aggregate["delivered"] == 20
    assert aggregate["payment_income"] == 500
    assert aggregate["actual_capex"] == 5021
    assert aggregate["infrastructure_capex"] == 21
    assert aggregate["vehicle_purchase"] == 5000
    assert aggregate["operating_costs"] is None
    assert aggregate["net_profit"] is None
    with pytest.raises(ValueError, match="exact selected"):
        aggregate_receipt(plan, services, [])


def test_captured_attempt16_cash_residual_requires_exact_command_witness(tmp_path):
    from pathlib import Path

    from app.simulation.openttd.freight_delivery import DeliveryPlan
    from app.simulation.openttd.freight_native_network import service_construction

    directory = Path("artifacts/runtime/openttd-15.3-first-freight-delivery-attempt16")
    if not (directory / "native-plan-1.json").exists():
        pytest.skip("optional retained native evidence not installed")
    plan = DeliveryPlan.model_validate_json((directory / "native-plan-1.json").read_bytes())
    records = {
        "inspect-1": DeliveryReadback.model_validate_json(
            (directory / "activate-1-response.json").read_bytes()
        )
    }
    for i in range(10):
        for kind in ("build", "read"):
            records[f"{kind}-{i}"] = DeliveryReadback.model_validate_json(
                (directory / f"s1-{kind}-{i}-response.json").read_bytes()
            )
    with pytest.raises(ValueError, match="native spending/readback mismatch"):
        service_construction(plan, records)
    other = DeliveryPlan.model_validate_json((directory / "native-plan-0.json").read_bytes())
    result = service_construction(
        plan, records, log_path=directory / "stderr.log", network_plans=(other.digest,)
    )
    assert result["construction_purchase_spending"] == 9515
    changes = result["unallocated_company_cash_changes"]
    assert len(changes) == 1
    assert changes[0]["stage"] == 4
    assert changes[0]["unallocated_company_cash_decrease"] == 1
    assert changes[0]["interval"] == "previous_read_to_build"
    assert changes[0]["expense_category"] == "UNKNOWN"
    assert changes[0]["before_digest"] == records["read-3"].digest
    assert changes[0]["after_digest"] == records["build-4"].digest
    broken = dict(records)
    values = list(records["read-4"].s)
    values[3] -= 1
    broken["read-4"] = records["read-4"].model_copy(update={"s": tuple(values)})
    concurrent = service_construction(
        plan, broken, log_path=directory / "stderr.log", network_plans=(other.digest,)
    )
    assert concurrent["construction_purchase_spending"] == 9515
    assert any(
        change["stage"] == 4
        and change["interval"] == "build_to_read"
        and change["unallocated_company_cash_decrease"] == 1
        and change["expense_category"] == "UNKNOWN"
        and change["before_digest"] == records["build-4"].digest
        and change["after_digest"] == broken["read-4"].digest
        for change in concurrent["unallocated_company_cash_changes"]
    )
    with pytest.raises(ValueError, match="native spending/readback mismatch"):
        service_construction(plan, broken)

    same_tick = dict(broken)
    same_values = list(broken["read-4"].s)
    same_values[0] = records["build-4"].s[0]
    same_tick["read-4"] = broken["read-4"].model_copy(update={"s": tuple(same_values)})
    with pytest.raises(ValueError, match="cash reconciliation chronology mismatch"):
        service_construction(
            plan, same_tick, log_path=directory / "stderr.log", network_plans=(other.digest,)
        )

    tampered = tmp_path / "stderr.log"
    tampered.write_text(
        (directory / "stderr.log")
        .read_text()
        .replace(
            f"plan={plan.digest} stage=4 result=1 quoted=307 cost=307 spent=307",
            f"plan={plan.digest} stage=4 result=1 quoted=307 cost=307 spent=308",
        )
    )
    with pytest.raises(ValueError, match="construction command quote/spending mismatch"):
        service_construction(plan, records, log_path=tampered, network_plans=(other.digest,))


def test_company_finance_reconciliation_replays_cash_without_inventing_opex(tmp_path):
    from pathlib import Path

    from app.simulation.openttd.freight_native_network import (
        financial_reconciliation,
        verify_financial_reconciliation,
    )

    directory = Path("artifacts/runtime/openttd-15.3-first-freight-delivery-attempt16")
    if not (directory / "service-receipt-0.json").exists():
        pytest.skip("optional retained native evidence not installed")
    receipt = json.loads((directory / "service-receipt-0.json").read_bytes())
    records = {
        name: DeliveryReadback.model_validate_json(
            (directory / f"{name}-response.json").read_bytes()
        )
        for name in ("select-0", "s0-park-read")
    }
    aggregate = dict(
        services=[receipt],
        actual_capex=receipt["construction_purchase_spending"],
        payment_income=receipt["payment_income"],
    )
    result = financial_reconciliation(directory, records, aggregate)
    assert result["operating_costs"] is None
    assert result["net_profit"] is None
    assert result["expense_category"] == "UNKNOWN"
    assert result["final_cash"] == (
        result["initial_cash"]
        - result["command_construction_purchase_costs"]
        + result["freight_revenue"]
        - result["unallocated_company_cash_decrease"]
    )
    # Replay uses retained endpoint values, not a receipt's claimed cash totals.
    (tmp_path / "capital-read-response.json").write_bytes(
        (directory / "capital-read-response.json").read_bytes()
    )
    sidecar = tmp_path / "financial-reconciliation.json"
    sidecar.write_text(json.dumps(result))
    assert verify_financial_reconciliation(tmp_path, records, aggregate) == result
    result["unallocated_company_cash_decrease"] += 1
    sidecar.write_text(json.dumps(result))
    with pytest.raises(ValueError, match="financial reconciliation replay mismatch"):
        verify_financial_reconciliation(tmp_path, records, aggregate)


def test_financial_reconciliation_version_rejects_unknown_versions():
    from app.simulation.openttd.freight_native_network import (
        validate_financial_reconciliation_version,
    )

    assert validate_financial_reconciliation_version({}) is None
    assert validate_financial_reconciliation_version({"financial_reconciliation_version": 1}) == 1
    for version in (True, 0, 2, "1"):
        with pytest.raises(ValueError, match="unsupported financial reconciliation version"):
            validate_financial_reconciliation_version({"financial_reconciliation_version": version})
