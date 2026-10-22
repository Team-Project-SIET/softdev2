"""Native finance deltas stay distinct from unavailable expense categories."""

import pytest

from app.simulation.openttd.freight_finance import (
    ContinuousRequest,
    reconcile_cash,
    reconcile_snapshots,
)


def row(month, cash, income, expenses, delivered, *, closed=(0, 0, 0), loan=0):
    return {
        "finance": dict(
            clock=dict(economy_year=1950, economy_month=month, economy_date=month * 30),
            cash=cash,
            loan_balance=loan,
            quarter_income=income,
            quarter_expenses=expenses,
            quarter_delivered=delivered,
            previous_quarter_income=closed[0],
            previous_quarter_expenses=closed[1],
            previous_quarter_delivered=closed[2],
        )
    }


def test_unexplained_attempt17_spending_is_not_opex():
    report = reconcile_cash(500000, 471492, 1018, 28459)
    assert report["unknown_cash_movements"] == -1067
    assert report["vehicle_operating_expenses"] is None
    assert report["operating_profit"] is None
    assert report["roi"] is None


def test_complete_accounting_supports_profit():
    report = reconcile_cash(1000, 950, 200, 100, 100, 25, 25)
    assert report["unknown_cash_movements"] == 0
    assert report["operating_profit"] == 50
    assert report["roi"] == -0.5


def test_quarter_rollover_repeated_deliveries_and_loan_change():
    rows = [
        row(3, 1000, 100, -10, 20),
        row(4, 1060, 20, -5, 4, closed=(150, -15, 30)),
        row(5, 1075, 50, -20, 10),
    ]
    result = reconcile_snapshots(rows)
    assert result["freight_revenue"] == 100
    assert result["delivered_cargo"] == 20
    assert result["company_quarter_expenses_signed"] == -25
    assert result["accounting_residual_after_total_expenses"] == 0
    assert result["vehicle_operating_expenses"] is None


def test_missing_quarter_is_rejected():
    with pytest.raises(ValueError, match="quarter observation gap"):
        reconcile_snapshots([row(3, 1000, 0, 0, 0), row(7, 1000, 0, 0, 0)])


def test_finite_service_requests():
    assert (
        b'"service":2'
        in ContinuousRequest(
            type="continuous-service", request_id="period-1-s2", service=2
        ).to_bytes()
    )
    with pytest.raises(ValueError, match="invalid continuous service"):
        ContinuousRequest(type="continuous-service", request_id="period-1-s3", service=3).to_bytes()


def test_controlled_squirrel_three_services_continuously_operate():
    import json

    from test_native_freight_network import network_vm

    from app.simulation.openttd.freight_delivery import DeliveryRequest
    from app.simulation.openttd.freight_finance import ContinuousReadback
    from app.simulation.openttd.freight_planning import PlanningSelectionRequest
    from app.simulation.openttd.proof.freight_delivery import staged_package

    vm = network_vm(3)
    package = staged_package(True, True, True, network_service_limit=3, continuous_years=5)
    parent = package["continuous-parent.nut"].decode()
    # The network VM already installed the same parent under its original name.
    vm.execute(
        parent.replace('require("network-parent.nut");', "").replace(
            "class NetworkFreightProof", "class ContinuousNetworkParent"
        )
    )
    code = package["main.nut"].decode().replace('require("continuous-parent.nut");', "")
    code = code.replace("extends NetworkFreightProof", "extends ContinuousNetworkParent")
    vm.execute(code)
    vm.execute("""
        ::GSDate = class extends GSDate {
            static function GetDayOfMonth(d){return 1;}
            static function GetDate(y,m,d){return 700000+(y-1950)*365;}
        };
        ::GSGameSettings <- class {static function GetValue(k){return 0;}};
        ::GSCompany = class extends GSCompany {
            static function GetLoanAmount(){return 100000;}
            static function GetAutoRenewStatus(c){return ::autorenew;}
            static function GetQuarterlyExpenses(c,q){return -15;}
        };
        ::GSVehicle = class extends GSVehicle {
            static VS_CRASHED=5;
            static function GetProfitLastYear(v){return 0;}
            static function GetRunningCost(v){return 200;}
        };
        ::autorenew <- false;
        ::bridge=ContinuousFreightProof();
    """)
    for n, shift in enumerate((0, 1536, 768)):
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
        vm.execute("::bridge.Handle(" + request.to_bytes().decode() + ");")
    for n in range(3):
        vm.execute(f"::bridge.LoadService({n});")
        for stage in range(10):
            request = DeliveryRequest(
                op="build", request_id=f"s{n}-build-{stage}", plan="a" * 64, arg=stage
            )
            vm.execute("::bridge.Handle(" + request.to_bytes().decode() + ");")
    request = ContinuousRequest(type="continuous-begin", request_id="continuous-begin")
    vm.execute("::autorenew=true;")
    blocked = request.model_copy(update={"request_id": "blocked-autorenew"})
    vm.execute("::bridge.Handle(" + blocked.to_bytes().decode() + ");")
    rejected = vm.get_roottable()["replies"]
    rejected = rejected[len(rejected) - 1]
    assert rejected["status"] == "rejected"
    assert rejected["request_id"] == blocked.request_id
    assert rejected["error"] == "CONTINUOUS_AUTORENEW_ENABLED"
    vm.execute("::autorenew=false;")
    vm.execute("::bridge.Handle(" + request.to_bytes().decode() + ");")
    replies = vm.get_roottable()["replies"]
    reply = replies[len(replies) - 1]

    def convert(value):
        if hasattr(value, "keys"):
            return {str(k): convert(value[k]) for k in value.keys()}
        if hasattr(value, "__len__") and not isinstance(value, str):
            return [convert(value[i]) for i in range(len(value))]
        return value

    raw = json.dumps(convert(reply), separators=(",", ":")).encode()
    assert len(raw) <= 1450
    begin = ContinuousReadback.parse_for(request, raw)
    assert begin.baseline_delivered == (0, 0, 0)
    vm.execute("""
        foreach(v,c in ::vehicles)if(!c.started||c.stopped)throw "SERVICE_NOT_CONTINUOUS";
        if(::vehicles.len()!=3)throw "VEHICLE_COUNT_CHANGED";
    """)
    vm.execute("""
        ::GSCargoMonitor = class extends GSCargoMonitor {
            static function GetIndustryDeliveryAmount(c,g,i,k){return 20;}
        };
    """)
    for cycle in range(2):
        request = ContinuousRequest(
            type="continuous-service", request_id=f"cycle-{cycle}", service=0
        )
        vm.execute("::bridge.Handle(" + request.to_bytes().decode() + ");")
        replies = vm.get_roottable()["replies"]
        raw = json.dumps(convert(replies[len(replies) - 1]), separators=(",", ":")).encode()
        service = ContinuousReadback.parse_for(request, raw)
        assert service.delivered == (cycle + 1) * 20
        assert service.revenue is None
        assert service.completed_delivery_cycles is None
    with pytest.raises(Exception, match="CONTINUOUS_OPERATION_SEALED"):
        vm.execute('::bridge.Handle({op="build"});')


def test_readback_refuses_duplicate_response_keys():
    from app.simulation.openttd.freight_finance import ContinuousReadback

    q = ContinuousRequest(type="continuous-company", request_id="bounded")
    with pytest.raises(ValueError, match="duplicate response key"):
        ContinuousReadback.parse_for(q, b'{"protocol":1,"protocol":1}')
    with pytest.raises(ValueError, match="1450 bytes"):
        ContinuousReadback.parse_for(q, b" " * 1451)


def test_continuous_native_rejection_is_prompt_and_retained(tmp_path):
    import asyncio
    import json
    import struct
    from types import SimpleNamespace

    from app.simulation.openttd.freight_finance import ContinuousReadback
    from app.simulation.openttd.gamescript_transport import SERVER_GAMESCRIPT
    from app.simulation.openttd.proof.freight_delivery import exchange

    request = ContinuousRequest(type="continuous-begin", request_id="blocked")
    raw = json.dumps(
        dict(
            protocol=1,
            type="continuous-begin-result",
            request_id="blocked",
            status="rejected",
            error="CONTINUOUS_AUTORENEW_ENABLED",
        )
    ).encode()
    sent = []
    receives = []

    async def send(payload):
        sent.append(payload)

    async def receive():
        receives.append(True)
        assert len(receives) == 1, "explicit rejection must never wait for another reply"
        return struct.pack("<HB", len(raw) + 4, SERVER_GAMESCRIPT) + raw + b"\0"

    with pytest.raises(
        ValueError, match="native continuous rejection: CONTINUOUS_AUTORENEW_ENABLED"
    ):
        asyncio.run(
            exchange(
                SimpleNamespace(send=send, receive=receive),
                request,
                tmp_path,
                response_type=ContinuousReadback,
            )
        )
    assert len(sent) == len(receives) == 1
    assert (tmp_path / "blocked-response.json").read_bytes() == raw


@pytest.mark.parametrize(
    "change",
    [
        {"protocol": True},
        {"request_id": "other"},
        {"type": "continuous-company-result"},
        {"error": ""},
        {"error": "x" * 161},
        {"extra": 1},
    ],
)
def test_continuous_rejection_requires_exact_correspondence(change):
    import json

    from app.simulation.openttd.freight_finance import ContinuousReadback

    request = ContinuousRequest(type="continuous-begin", request_id="blocked")
    reply = dict(
        protocol=1,
        type="continuous-begin-result",
        request_id="blocked",
        status="rejected",
        error="CONTINUOUS_AUTORENEW_ENABLED",
    )
    reply.update(change)
    with pytest.raises(ValueError, match="invalid continuous rejection"):
        ContinuousReadback.parse_for(request, json.dumps(reply).encode())
