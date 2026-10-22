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
    booleans = {
        "infinite_money",
        "attempted",
        "completed",
        "resumed",
        "autorenew_set",
        "autorenew_enabled",
    }
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


@pytest.mark.parametrize("continuous", [False, True])
def test_funding_replay_requires_exact_correlated_four_frames(tmp_path, continuous):
    from app.simulation.openttd.gamescript_transport import SERVER_GAMESCRIPT, encode_gamescript
    from app.simulation.openttd.scenario_capital import (
        ScenarioCapitalReadback,
        ScenarioCapitalRequest,
        verify_capital,
    )

    vm = continuous_capital_vm() if continuous else capital_vm()
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
    if continuous:
        from app.simulation.openttd.scenario_capital import (
            company_policy_provenance,
            fixed_fleet_policy,
        )

        for name in ("before", "qualified", "after"):
            (tmp_path / f"{name}.sav").write_bytes(name.encode())
        proof.write_json(
            tmp_path / "PRELAUNCH.json",
            dict(company_policy=fixed_fleet_policy(), company_policy_provenance_version=2),
        )
        proof.write_json(tmp_path / "result.json", dict(company_policy_mutations=1))
        proof.write_json(
            tmp_path / "company-policy.json", company_policy_provenance(tmp_path, funding)
        )
        proof.write_json(
            tmp_path / "company-policy-final.json",
            company_policy_provenance(tmp_path, funding, complete=True),
        )
    assert proof.verify_capital_frames(tmp_path, frames) == funding
    if continuous:
        original = (tmp_path / "company-policy-final.json").read_bytes()
        (tmp_path / "company-policy-final.json").write_text("{}")
        with pytest.raises(ValueError, match="final company policy save correspondence"):
            proof.verify_capital_frames(tmp_path, frames)
        (tmp_path / "company-policy-final.json").write_bytes(original)
        metadata_path = tmp_path / "PRELAUNCH.json"
        metadata = metadata_path.read_bytes()
        metadata_path.write_text(json.dumps(dict(company_policy=fixed_fleet_policy())))
        with pytest.raises(ValueError, match="company policy save correspondence mismatch"):
            proof.verify_capital_frames(tmp_path, frames)
        metadata_path.write_bytes(metadata)
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


def continuous_capital_vm():
    vm = capital_vm()
    vm.execute("""
        ::autorenew <- true; ::setter_ok <- true; ::readback_stuck <- false;
        ::policy_calls <- 0; ::policy_company <- -1;
        ::GSCompanyMode = class {
            constructor(c){::policy_company=c;}
            static function IsDeity(){return ::deity;}
            static function IsValid(){return ::valid_company && ::policy_company==0;}
        };
        ::GSCompany = class extends GSCompany {
            static function SetAutoRenewStatus(v){
                if(!GSCompanyMode.IsValid())throw "INVALID_POLICY_CONTEXT";
                ::policy_calls++;if(::setter_ok&&!::readback_stuck)::autorenew=v;return ::setter_ok;
            }
            static function GetAutoRenewStatus(c){return ::autorenew;}
        };
    """)
    package = proof.staged_package(True, True, True, "high-budget-500k", 3, 5)
    vm.execute(
        package["funding.nut"]
        .decode()
        .replace("class ScenarioCapitalFunding", "class ContinuousFunding")
    )
    vm.execute("::funding=ContinuousFunding();")
    return vm


def test_continuous_company_policy_disables_native_default_and_persists():
    vm = continuous_capital_vm()
    _, response = send(vm)
    assert response["status"] == "FUNDED"
    assert not bool(vm.get_roottable()["autorenew"])
    assert int(vm.get_roottable()["policy_calls"]) == 1
    assert len(json.dumps(response, separators=(",", ":")).encode()) <= 768
    assert response["policy_version"] == 1
    assert response["policy_company"] == 0
    assert response["autorenew_set"] is True
    assert response["autorenew_enabled"] is False
    vm.execute("::saved<-funding.Save();::funding=ContinuousFunding();funding.Load(saved);")
    _, loaded = send(vm, "read")
    assert loaded["autorenew_enabled"] is False
    vm.execute("::autorenew=true;")
    with pytest.raises(Exception, match="COMPANY_POLICY_SAVE_MISMATCH"):
        vm.execute("::funding=ContinuousFunding();funding.Load(saved);")


@pytest.mark.parametrize("enabled", [True, False])
def test_fixed_policy_setter_and_readback_even_when_already_disabled(enabled):
    vm = continuous_capital_vm()
    vm.execute("::autorenew=" + str(enabled).lower() + ";")
    request, response = send(vm)
    validate_capital_response(request, response)
    assert not response["autorenew_enabled"]
    assert response["autorenew_set"]
    assert int(vm.get_roottable()["policy_calls"]) == 1


@pytest.mark.parametrize("change", ["::setter_ok=false;", "::readback_stuck=true;"])
def test_fixed_policy_rejected_initialization_does_not_fund(change):
    vm = continuous_capital_vm()
    vm.execute(change)
    request, response = send(vm)
    assert response["status"] == "COMPANY_POLICY_INITIALIZATION_FAILED"
    assert int(vm.get_roottable()["gifts"]) == 0
    assert not response["completed"]
    with pytest.raises(ValueError, match="rejected"):
        validate_capital_response(request, response)


def test_fixed_policy_invalid_company_never_sets():
    vm = continuous_capital_vm()
    vm.execute("::valid_company=false;")
    _, response = send(vm)
    assert response["status"] == "INVALID_COMPANY"
    assert int(vm.get_roottable()["policy_calls"]) == 0
    assert int(vm.get_roottable()["gifts"]) == 0


def test_policy_optional_receipt_fields_preserve_historical_funding():
    from app.simulation.openttd.scenario_capital import (
        ScenarioCapitalReadback,
        ScenarioCapitalRequest,
        verify_capital,
    )

    vm = capital_vm()
    _, initial = send(vm)
    _, check = send(vm, "read")
    a = ScenarioCapitalReadback.parse_for(
        ScenarioCapitalRequest(request_id=initial["request_id"], op="initialize"),
        json.dumps(initial).encode(),
    )
    b = ScenarioCapitalReadback.parse_for(
        ScenarioCapitalRequest(request_id=check["request_id"], op="read"),
        json.dumps(check).encode(),
    )
    receipt = verify_capital(a, b)
    assert "policy_version" not in receipt
    vm = continuous_capital_vm()
    req, response = send(vm)
    response["policy_company"] = 1
    with pytest.raises(ValueError, match="policy readback"):
        validate_capital_response(req, response)


def test_policy_save_digest_correspondence_rejects_modified_save(tmp_path):
    from app.simulation.openttd.scenario_capital import company_policy_provenance

    financing = dict(
        policy_version=1,
        policy_company=0,
        autorenew_set=True,
        autorenew_enabled=False,
        independently_verified=True,
    )
    for name in ("before", "qualified", "after"):
        (tmp_path / f"{name}.sav").write_bytes(name.encode())
    original = company_policy_provenance(tmp_path, financing, complete=True)
    (tmp_path / "before.sav").write_bytes(b"modified")
    assert company_policy_provenance(tmp_path, financing, complete=True) != original
    financing["autorenew_set"] = False
    with pytest.raises(ValueError, match="required native"):
        company_policy_provenance(tmp_path, financing)


def test_actual_continuous_packaged_save_callback_retains_policy():
    from test_native_freight_network import network_vm

    staged = proof.staged_package(True, True, True, "high-budget-500k", 3, 5)
    vm = network_vm(3)
    for name in (
        "funding.nut",
        "delivery.nut",
        "demo-world.nut",
        "network-parent.nut",
        "continuous-parent.nut",
        "main.nut",
    ):
        code = staged[name].decode()
        code = "\n".join(line for line in code.splitlines() if not line.startswith("require("))
        vm.execute(code)
    vm.execute("""
        ::GSCompany = class extends GSCompany {
            static function GetAutoRenewStatus(c){return false;}
        };
        ::funded <- ContinuousFreightProof();
        ::funded.capital_funding=ScenarioCapitalFunding();
        ::funded.capital_funding.attempted=true;
        ::funded.capital_funding.completed=true;
        ::funded.capital_funding.autorenew_set=true;
        ::saved <- funded.Save();
        if(saved.scenario_capital.schema!=2||saved.scenario_capital.autorenew_enabled)
            throw "MISSING_POLICY_SAVE";
        ::funded.Load(1,saved);
        if(!funded.capital_funding.autorenew_set)throw "MISSING_POLICY_LOAD";
        ::GSCompany = class extends GSCompany {
            static function GetAutoRenewStatus(c){return true;}
        };
    """)
    with pytest.raises(Exception, match="COMPANY_POLICY_SAVE_MISMATCH"):
        vm.execute("::funded.Load(1,saved);")


def test_continuous_policy_initial_and_final_persistence_lifecycle(tmp_path, monkeypatch):
    """Drive actual run() through both policy writes without native runtime access."""
    import asyncio
    import shutil
    from dataclasses import dataclass
    from types import SimpleNamespace

    from app.simulation.openttd import freight_native_network
    from app.simulation.openttd.scenario_capital import (
        ScenarioCapitalReadback,
        company_policy_provenance,
        fixed_fleet_policy,
    )

    root = tmp_path / "world"
    logs = root / "logs"
    logs.mkdir(parents=True)
    key = root / "admin-secret"
    key.write_bytes(proof.AuthorizedKey.generate()._secret)
    prepared = SimpleNamespace(
        directory=tmp_path,
        key_path=key,
        endpoints=(1, 2),
        spec=SimpleNamespace(
            workspace=SimpleNamespace(root=root, logs=logs, close=lambda: shutil.rmtree(root))
        ),
    )
    proof.write_json(
        tmp_path / "PRELAUNCH.json",
        dict(
            budgets=dict(total_seconds=10),
            planner=True,
            network=True,
            scenario="high-budget-500k",
            continuous_years=5,
            company_policy=fixed_fleet_policy(),
            company_policy_provenance_version=2,
        ),
    )

    @dataclass
    class Welcome:
        revision: str = "15.3"
        seed: int = 42
        width: int = 64
        height: int = 64

    class Session:
        protocol = SimpleNamespace()
        state = proof.AuthState.ACTIVE
        welcome = Welcome()

        @classmethod
        async def connect_secure(cls, *args, **kwargs):
            return cls()

        async def authenticate(self, *args, **kwargs):
            pass

    class Backend:
        process = None

        async def launch(self, p):
            self.process = object()

        async def cleanup(self, p):
            key.unlink()
            return dict(reaped=True, cleanup_error=[])

    class Accounting:
        def __init__(self, frames):
            pass

        def enter(self, *args):
            pass

        def observe(self, *args):
            pass

        def begin_funding(self):
            pass

        def end_funding(self):
            pass

    class Transport:
        def __init__(self, *args):
            pass

        async def subscribe(self):
            pass

    vm = continuous_capital_vm()

    async def exchange(session, request, *args, **kwargs):
        _, response = send(vm, request.op)
        response["request_id"] = request.request_id
        return ScenarioCapitalReadback.parse_for(request, json.dumps(response).encode())

    async def save(backend, p, name):
        (tmp_path / f"{name}.sav").write_bytes(name.encode())
        return proof.sha256(tmp_path / f"{name}.sav")

    async def execute_network(backend, p, *args):
        await save(backend, p, "qualified")
        await save(backend, p, "after")

    async def wait(*args):
        pass

    monkeypatch.setattr(proof, "preflight", lambda p: None)
    monkeypatch.setattr(proof, "backend_for", lambda m: Backend())
    monkeypatch.setattr(proof, "PlannerDeliverySession", Session)
    monkeypatch.setattr(proof, "ScenarioPlanningAccounting", Accounting)
    monkeypatch.setattr(proof, "GameScriptTransport", Transport)
    monkeypatch.setattr(proof, "exchange", exchange)
    monkeypatch.setattr(proof, "save", save)
    monkeypatch.setattr(proof, "wait_log", wait)
    monkeypatch.setattr(proof, "verify_cleanup_endpoints", lambda *args: {})
    monkeypatch.setattr(freight_native_network, "execute_network", execute_network)
    result = asyncio.run(proof.run(prepared))
    assert result["status"] == "NATIVE_FIVE_YEAR_CONTINUOUS_VERIFIED", result
    financing = json.loads((tmp_path / "scenario-capital.json").read_bytes())
    assert json.loads((tmp_path / "company-policy.json").read_bytes()) == company_policy_provenance(
        tmp_path, financing
    )
    assert json.loads(
        (tmp_path / "company-policy-final.json").read_bytes()
    ) == company_policy_provenance(tmp_path, financing, complete=True)
