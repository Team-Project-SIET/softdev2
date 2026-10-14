"""Controlled finite scenario funding; these API doubles provide no native proof."""

import json
import socket
import struct
import subprocess
from pathlib import Path

import pytest
from squirrel import SQVM

from app.simulation.openttd.proof import freight_delivery as proof
from app.simulation.openttd.scenario_capital import (
    capital_request,
    financial_preset,
    validate_capital_response,
)


@pytest.fixture(autouse=True)
def no_native(monkeypatch):
    def forbidden(*a, **kw):
        pytest.fail("controlled capital tests launched or connected")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def capital_vm():
    vm = SQVM()
    vm.execute("""
        ::funds <- 100000; ::loan <- 100000; ::deity <- true; ::valid_company <- true;
        ::infinite <- false; ::gifts <- 0; ::replies <- []; ::income <- 0; ::profit <- 0;
        ::GSCompanyMode <- class {
            constructor(company) {}
            static function IsDeity(){return ::deity;}
            static function IsValid(){return ::valid_company;}
        };
        ::GSCompany <- class {
            static EXPENSES_OTHER=13;
            static CURRENT_QUARTER=0;
            static function ResolveCompanyID(c){return ::valid_company?c:-1;}
            static function GetBankBalance(c){return ::funds;}
            static function GetLoanAmount(){return ::loan;}
            static function GetQuarterlyIncome(c,q){return ::income;}
            static function GetQuarterlyExpenses(c,q){return ::profit;}
            static function ChangeBankBalance(c,delta,expense,tile){
                if(!GSCompanyMode.IsDeity()||expense!=13||tile!=-1)throw "bad deity gift";
                ::gifts++;::funds+=delta;return true;
            }
        };
        ::GSGameSettings <- class {
            static function IsValid(n){return n=="difficulty.infinite_money";}
            static function GetValue(n){return ::infinite?1:0;}
        };
        ::GSVehicleList <- class {function Count(){return 0;}};
        ::GSMap <- class {static TILE_INVALID=-1;};
        ::GSAdmin <- class {static function Send(r){::replies.append(r);return true;}};
        ::GSLog <- class {static function Info(s){}};
    """)
    vm.execute(Path("app/simulation/openttd/freight_delivery_package/funding.nut").read_text())
    vm.execute("::funding <- ScenarioCapitalFunding();")
    return vm


def send(vm, op="initialize", *, preplanning=True):
    request = capital_request("CONTROLLED-" + op, op)
    vm.execute("funding.Handle(" + json.dumps(request) + "," + str(preplanning).lower() + ");")
    replies = vm.get_roottable()["replies"]
    response = replies[len(replies) - 1]
    strings = {"type", "request_id", "preset", "status"}
    booleans = {"infinite_money", "attempted", "completed", "resumed"}
    return request, {
        str(k): str(response[k])
        if str(k) in strings
        else bool(response[k])
        if str(k) in booleans
        else int(response[k])
        for k in response.keys()
    }


def test_finite_deity_gift_sets_exact_cash_preserves_loan_and_separate_income():
    vm = capital_vm()
    request, response = send(vm)
    validate_capital_response(request, response)
    assert response["balance_before"] == response["loan_before"] == response["loan_after"] == 100000
    assert response["delta"] == 400000
    assert response["balance_after"] == 500000
    assert not response["infinite_money"]
    root = vm.get_roottable()
    assert int(root["gifts"]) == 1
    assert int(root["income"]) == int(root["profit"]) == 0
    request, response = send(vm, "read")
    validate_capital_response(request, response, independent=True)


@pytest.mark.parametrize(
    "change,status",
    [
        ("::deity=false;", "INVALID_DEITY"),
        ("::valid_company=false;", "INVALID_COMPANY"),
        ("::infinite=true;", "INFINITE_MONEY_FORBIDDEN"),
    ],
)
def test_invalid_funding_prerequisites_never_mutate(change, status):
    vm = capital_vm()
    vm.execute(change)
    request, response = send(vm)
    assert response["status"] == status
    assert int(vm.get_roottable()["gifts"]) == 0
    assert int(vm.get_roottable()["funds"]) == 100000
    with pytest.raises(ValueError, match="rejected"):
        validate_capital_response(request, response)


def test_duplicate_and_reloaded_funding_never_repeats_gift():
    vm = capital_vm()
    send(vm)
    _, response = send(vm)
    assert response["status"] == "FUNDING_ALREADY_ATTEMPTED"
    vm.execute("::saved <- funding.Save();::funding=ScenarioCapitalFunding();funding.Load(saved);")
    _, response = send(vm)
    assert response["status"] == "RESUMED_FUNDING_FORBIDDEN"
    assert response["completed"]
    assert int(vm.get_roottable()["gifts"]) == 1
    assert int(vm.get_roottable()["funds"]) == 500000


def test_resume_even_unfunded_state_and_postplanning_reject():
    vm = capital_vm()
    _, response = send(vm, preplanning=False)
    assert response["status"] == "FUNDING_AFTER_PLANNING_FORBIDDEN"
    vm.execute("::saved <- funding.Save();::funding=ScenarioCapitalFunding();funding.Load(saved);")
    _, response = send(vm)
    assert response["status"] == "RESUMED_FUNDING_FORBIDDEN"
    assert int(vm.get_roottable()["gifts"]) == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("balance_after", 499999),
        ("loan_after", 100001),
        ("delta", 400001),
        ("balance_before", True),
        ("infinite_money", True),
        ("resumed", True),
        ("income_after", 400000),
        ("expenses_after", -400000),
        ("vehicles", 1),
    ],
)
def test_cash_loan_and_finite_provenance_tampering_rejected(field, value):
    request, response = send(capital_vm())
    response[field] = value
    with pytest.raises(ValueError):
        validate_capital_response(request, response)


def test_only_named_finite_preset_supported():
    preset = financial_preset("high-budget-500k")
    assert preset["target_balance_gbp"] == 500000
    assert preset["infinite_money"] is False
    assert preset["loan_policy"] == "unchanged"
    with pytest.raises(ValueError):
        financial_preset("infinite-money")


@pytest.mark.parametrize("budget", [500000, 18000])
def test_finite_preset_prelaunch_keeps_cash_separate_from_hard_spending_cap(budget):
    metadata = {
        "scenario": "high-budget-500k",
        "financial_preset": financial_preset("high-budget-500k"),
        "planning_budget_gbp": str(budget),
        "world": {"seed": 42},
        "demo": True,
        "planner": True,
    }
    proof.validate_capital_prelaunch(metadata, "[difficulty]\ninfinite_money = false\n")
    assert metadata["planning_budget_gbp"] == str(budget)
    assert metadata["financial_preset"]["target_balance_gbp"] == 500000
    with pytest.raises(ValueError, match="infinite money forbidden"):
        proof.validate_capital_prelaunch(metadata, "[difficulty]\ninfinite_money = true\n")


@pytest.mark.parametrize("budget", ["NaN", "Infinity", "-1", "0", "18000.5"])
def test_preparation_rejects_invalid_spending_cap_before_side_effects(tmp_path, budget):
    output = tmp_path / "openttd-15.3-first-freight-delivery-attempt1"
    with pytest.raises(ValueError, match="finite positive integer"):
        proof.prepare(
            output, demo=True, planner=True, scenario="high-budget-500k", planning_budget=budget
        )
    assert not output.exists()


def test_capital_staged_main_exposes_actual_persistent_save_and_load():
    from test_native_freight_network import network_vm

    staged = proof.staged_package(True, True, True, "high-budget-500k")
    vm = network_vm()
    for name in ("funding.nut", "delivery.nut", "demo-world.nut", "network-parent.nut", "main.nut"):
        code = staged[name].decode()
        code = "\n".join(line for line in code.splitlines() if not line.startswith("require("))
        vm.execute(code)
    vm.execute("::funded <- NetworkFreightProof();::saved <- funded.Save();funded.Load(1,saved);")
    assert bool(vm.get_roottable()["funded"]["capital_funding"]["resumed"])
    assert b"function LoadService(n)" in staged["main.nut"]
    assert b"LoadService(q.arg)" in staged["main.nut"]


@pytest.mark.parametrize("initial,delta,gifts", [(750000, -250000, 1), (500000, 0, 0)])
def test_funding_normalizes_existing_cash_without_changing_loan(initial, delta, gifts):
    vm = capital_vm()
    vm.execute(f"::funds={initial};")
    request, response = send(vm)
    validate_capital_response(request, response)
    assert response["delta"] == delta
    assert response["balance_after"] == 500000
    assert response["loan_before"] == response["loan_after"] == 100000
    assert int(vm.get_roottable()["gifts"]) == gifts


@pytest.mark.parametrize("budget", [None, 18000])
@pytest.mark.parametrize("finance_only", [True, False])
def test_python_preparation_seals_finite_preset_and_effective_hard_cap(
    tmp_path, monkeypatch, budget, finance_only
):
    monkeypatch.setattr(proof.DemoBackend, "launch", lambda *a: pytest.fail("prepare launched"))
    monkeypatch.setattr(
        proof.DeliverySession, "connect_secure", lambda *a: pytest.fail("prepare connected")
    )
    prepared = proof.prepare(
        tmp_path / "openttd-15.3-first-freight-delivery-attempt1",
        demo=True,
        planner=True,
        network=not finance_only,
        scenario="high-budget-500k",
        planning_budget=budget,
        finance_only=finance_only,
    )
    try:
        proof.preflight(prepared)
        seal = json.loads((prepared.directory / "PRELAUNCH.json").read_text())
        assert seal["planning_budget_gbp"] == str(500000 if budget is None else budget)
        assert seal["financial_preset"]["target_balance_gbp"] == 500000
        assert seal["world"]["seed"] == 42
        assert not (prepared.directory / "CLAIM.json").exists()
        assert "infinite_money = false" in prepared.spec.workspace.config.read_text()
    finally:
        prepared.spec.workspace.close()


def test_funding_four_frames_preserve_setup_and_qualification_accounting():
    from app.simulation.openttd.gamescript_transport import ADMIN_GAMESCRIPT, SERVER_GAMESCRIPT

    frames = []
    accounting = proof.ScenarioPlanningAccounting(frames)

    def frame(kind):
        return struct.pack("<HB", 3, kind)

    for _ in range(2):
        accounting.observe("inbound", frame(100))
    accounting.enter("setup")
    for _ in range(3):
        accounting.observe("outbound", frame(2))
    accounting.begin_funding()
    for _ in range(2):
        accounting.observe("outbound", frame(ADMIN_GAMESCRIPT))
        accounting.observe("inbound", frame(SERVER_GAMESCRIPT))
    accounting.end_funding()
    assert accounting.snapshot()["categories"]["setup"] == 3
    assert len(frames) == 9
    accounting.enter("clock")
    accounting.observe("outbound", frame(ADMIN_GAMESCRIPT))
    assert accounting.snapshot()["categories"]["clock"] == 1
    with pytest.raises(ValueError):
        accounting.begin_funding()


def test_funding_replay_requires_exact_correlated_four_frames(tmp_path):
    from app.simulation.openttd.gamescript_transport import SERVER_GAMESCRIPT, encode_gamescript
    from app.simulation.openttd.scenario_capital import (
        ScenarioCapitalReadback,
        ScenarioCapitalRequest,
        verify_capital,
    )

    vm = capital_vm()
    frames, readbacks = [], []
    for request in (
        ScenarioCapitalRequest(request_id="capital-initialize", op="initialize"),
        ScenarioCapitalRequest(request_id="capital-read", op="read"),
    ):
        request_id = request.request_id
        _, response = send(vm, request.op)
        response["request_id"] = request_id
        raw = request.to_bytes()
        payload = json.dumps(response, separators=(",", ":")).encode()
        (tmp_path / f"{request_id}-request.json").write_bytes(raw)
        (tmp_path / f"{request_id}-response.json").write_bytes(payload)
        frames.extend(
            [
                ["outbound", encode_gamescript(raw).hex()],
                [
                    "inbound",
                    (
                        struct.pack("<HB", len(payload) + 4, SERVER_GAMESCRIPT) + payload + b"\0"
                    ).hex(),
                ],
            ]
        )
        readbacks.append(ScenarioCapitalReadback.parse_for(request, payload))
    funding = verify_capital(*readbacks)
    (tmp_path / "scenario-capital.json").write_text(json.dumps(funding))
    assert proof.verify_capital_frames(tmp_path, frames) == funding
    with pytest.raises(ValueError, match="exactly four"):
        proof.verify_capital_frames(tmp_path, frames[:-1])
    changed = [list(item) for item in frames]
    changed[0][0] = "inbound"
    with pytest.raises(ValueError, match="continuous secure frames"):
        proof.verify_capital_frames(tmp_path, changed)
    from app.simulation.openttd.observation_protocol import MalformedMessage

    changed = [list(item) for item in frames]
    unterminated = bytes.fromhex(changed[1][1])[:-1]
    changed[1][1] = (struct.pack("<H", len(unterminated)) + unterminated[2:]).hex()
    with pytest.raises(MalformedMessage, match="terminated string"):
        proof.verify_capital_frames(tmp_path, changed)


def test_capital_allowance_never_relaxes_setup_or_accepts_fifth_funding_frame():
    from app.simulation.openttd.gamescript_transport import ADMIN_GAMESCRIPT, SERVER_GAMESCRIPT

    def ready():
        accounting = proof.ScenarioPlanningAccounting([])
        for _ in range(2):
            accounting.observe("inbound", struct.pack("<HB", 3, 100))
        accounting.enter("setup")
        for _ in range(3):
            accounting.observe("outbound", struct.pack("<HB", 3, 2))
        return accounting

    accounting = ready()
    with pytest.raises(ValueError):
        accounting.observe("outbound", struct.pack("<HB", 3, 2))
    accounting = ready()
    accounting.begin_funding()
    for _ in range(2):
        accounting.observe("outbound", struct.pack("<HB", 3, ADMIN_GAMESCRIPT))
        accounting.observe("inbound", struct.pack("<HB", 3, SERVER_GAMESCRIPT))
    with pytest.raises(ValueError, match="excessive capital frame"):
        accounting.observe("outbound", struct.pack("<HB", 3, ADMIN_GAMESCRIPT))
    assert accounting.snapshot()["categories"]["setup"] == 3
    assert accounting.failed
    with pytest.raises(ValueError):
        accounting.end_funding()
    with pytest.raises(ValueError):
        accounting.begin_funding()
    with pytest.raises(ValueError):
        accounting.enter("clock")


def test_bad_funding_frame_cannot_be_replaced_with_valid_frame():
    from app.simulation.openttd.gamescript_transport import ADMIN_GAMESCRIPT

    accounting = proof.ScenarioPlanningAccounting([])
    for _ in range(2):
        accounting.observe("inbound", struct.pack("<HB", 3, 100))
    accounting.enter("setup")
    for _ in range(3):
        accounting.observe("outbound", struct.pack("<HB", 3, 2))
    accounting.begin_funding()
    with pytest.raises(ValueError, match="capital frame"):
        accounting.observe("inbound", struct.pack("<HB", 3, ADMIN_GAMESCRIPT))
    with pytest.raises(ValueError, match="no resume"):
        accounting.observe("outbound", struct.pack("<HB", 3, ADMIN_GAMESCRIPT))
    assert accounting.funding_count == 0
    assert len(accounting.retained_frames) == 7
