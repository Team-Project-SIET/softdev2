"""Actual new Squirrel handler, controlled native APIs, and retained receipt admission."""

import asyncio
import json
from pathlib import Path

import pytest
from squirrel import SQVM

from app.simulation.openttd.admin_protocol import encode_admin_frame
from app.simulation.openttd.gamescript_transport import (
    SERVER_GAMESCRIPT,
    GameScriptSession,
    encode_gamescript,
)
from app.simulation.openttd.proof.harness import manifest, sha256, write_json
from app.simulation.openttd.proof.road_mutation import (
    PACKAGES,
    RoadSecureSession,
    preflight,
    prepare,
    run,
    verify_receipt,
)
from app.simulation.openttd.road_mutation import (
    RoadReadback,
    RoadRequest,
    admit_segment,
    verify_segment,
)
from app.simulation.openttd.secure_admin import AuthState

SEAL = "a" * 64
SAVE = "b" * 64


def vm_for(*, funds=100000, invalid=False, rejected=False, mismatch=False, vacant=True):
    vm = SQVM()
    vm.execute(Path("tests/fixtures/gamescript_api_15.nut").read_text())
    vm.execute(f"""
        ::funds <- {funds}; ::valid_company <- {str(not invalid).lower()};
        ::reject <- {str(rejected).lower()}; ::mismatch <- {str(mismatch).lower()};
        ::vacant <- {str(vacant).lower()}; ::built <- false;
        ::account <- 0; ::tests <- {{}}; ::real_calls <- 0; ::test_calls <- 0;
        class GSCompany {{
            static COMPANY_INVALID = -1;
            static function ResolveCompanyID(c) {{ return ::valid_company && c == 0 ? 0 : -1; }}
            static function GetBankBalance(c) {{ return ::funds; }}
        }}
        class GSCompanyMode {{
            constructor(c) {{ if(c != 0) throw "company"; }}
            static function IsValid() {{ return ::valid_company; }}
        }}
        class GSAccounting {{
            constructor() {{ ::account++; }}
            function GetCosts() {{ return 20; }}
        }}
        class GSTestMode {{ constructor() {{ ::tests[::account] <- true; }} }}
        class GSMap {{
            static function IsValidTile(t) {{ return t > 0 && t < 4095; }}
            static function DistanceManhattan(a,b) {{
                return abs(a%64-b%64) + abs(a/64-b/64);
            }}
        }}
        class GSTile {{
            static TRANSPORT_ROAD=0; static TRANSPORT_RAIL=1;
            static TRANSPORT_WATER=2; static TRANSPORT_AIR=3;
            static function IsBuildable(t) {{ return ::vacant && !::built; }}
            static function GetSlope(t) {{ return 0; }}
            static function GetMinHeight(t) {{ return 1; }}
            static function GetOwner(t) {{ return ::built ? 0 : -1; }}
            static function IsWaterTile(t) {{ return false; }}
            static function IsCoastTile(t) {{ return false; }}
            static function HasTreeOnTile(t) {{ return false; }}
            static function IsFarmTile(t) {{ return false; }}
            static function IsRockTile(t) {{ return false; }}
            static function IsRoughTile(t) {{ return false; }}
            static function HasTransportType(t,kind) {{ return ::built && kind==0; }}
        }}
        class GSRoad {{
            static ROADTYPE_ROAD=0;
            static function SetCurrentRoadType(t) {{ if(t!=0) throw "road type"; }}
            static function GetCurrentRoadType() {{ return 0; }}
            static function IsRoadTypeAvailable(t) {{ return true; }}
            static function IsRoadTile(t) {{ return ::built; }}
            static function AreRoadTilesConnected(a,b) {{ return ::built; }}
            static function BuildRoad(a,b) {{
                if(::account in ::tests) {{ ::test_calls++; return true; }}
                ::real_calls++;
                if(::reject) return false;
                ::funds -= 20;
                if(!::mismatch) ::built=true;
                return true;
            }}
        }}
    """)
    vm.execute((PACKAGES / "road_mutation_package/main.nut").read_text())
    vm.execute("::bridge <- RoadMutationProof();")
    return vm


def request(op="inspect", **changes):
    data = dict(
        op=op, request_id=op + "-1", plan=SEAL, company=0, start=650, end=651, max_cost=10000
    )
    data.update(changes)
    return RoadRequest(**data)


def handle(vm, q):
    vm.execute("bridge.Handle(" + q.to_bytes().decode() + ");")
    replies = vm.get_roottable()["replies"]
    response = replies[len(replies) - 1]
    data = {}
    for key in response.keys():
        k = str(key)
        v = response[k]
        data[k] = (
            str(v)
            if k in ("op", "request_id", "plan", "status")
            else (bool(v) if k in ("eligible", "road0", "road1", "connected") else int(v))
        )
    return RoadReadback.parse_for(q, json.dumps(data, separators=(",", ":")).encode())


def controlled_success(vm):
    before = handle(vm, request())
    intent = admit_segment(before, prelaunch_digest=SEAL, source_save_digest=SAVE, max_cost=10000)
    built = handle(vm, request("build", plan=intent.digest))
    after = handle(vm, request("read", plan=intent.digest))
    return intent, before, built, after


def test_actual_handler_owned_state_change_and_plan_bound_receipt():
    vm = vm_for()
    intent, before, built, after = controlled_success(vm)
    receipt = verify_segment(intent, before, built, after)
    assert receipt["plan_digest"] == intent.digest
    assert receipt["owned_connected_road"] is True
    assert before.funds == 100000 and after.funds == 99980
    assert int(vm.get_roottable()["real_calls"]) == 1
    assert int(vm.get_roottable()["test_calls"]) == 2
    assert not before.connected and after.connected
    assert (before.owner0, before.owner1) == (-1, -1)
    assert (after.owner0, after.owner1) == (0, 0)
    again = handle(vm, request("build", request_id="build-2", plan=intent.digest))
    assert again.status == "ALREADY_ATTEMPTED"
    assert int(vm.get_roottable()["real_calls"]) == 1


@pytest.mark.parametrize(
    "kwargs,status",
    [
        ({"funds": 0}, "INSUFFICIENT_FUNDS"),
        ({"invalid": True}, "INVALID_COMPANY"),
        ({"vacant": False}, "NOT_BUILDABLE"),
    ],
)
def test_admission_failure_cannot_construct(kwargs, status):
    vm = vm_for(**kwargs)
    before = handle(vm, request())
    assert before.status == status
    with pytest.raises(ValueError):
        admit_segment(before, prelaunch_digest=SEAL, source_save_digest=SAVE, max_cost=10000)
    assert int(vm.get_roottable()["real_calls"]) == 0


@pytest.mark.parametrize(
    "kwargs,status",
    [
        ({"rejected": True}, "REJECTED"),
        ({"mismatch": True}, "READBACK_MISMATCH"),
    ],
)
def test_real_command_failure_is_not_success_and_cannot_retry(kwargs, status):
    vm = vm_for(**kwargs)
    intent, before, built, after = controlled_success(vm)
    assert built.status == status
    with pytest.raises(ValueError):
        verify_segment(intent, before, built, after)
    assert handle(vm, request("build", request_id="build-2")).status == "ALREADY_ATTEMPTED"
    assert int(vm.get_roottable()["real_calls"]) == 1


@pytest.mark.parametrize(
    "field,value", [("owner0", 1), ("connected", False), ("plan", "c" * 64), ("road1", False)]
)
def test_independent_readback_corruption_rejected(field, value):
    intent, before, built, after = controlled_success(vm_for())
    with pytest.raises(ValueError):
        verify_segment(intent, before, built, after.model_copy(update={field: value}))


def test_native_test_cost_limit_and_invalid_location():
    vm = vm_for()
    assert handle(vm, request(max_cost=19)).status == "COST_LIMIT"
    # Native bridge also enforces adjacency, independent of Python admission.
    vm.execute(
        'bridge.Handle({protocol=1,op="inspect",request_id="bad-location",'
        'plan="' + SEAL + '",company=0,start=650,end=652,max_cost=10000});'
    )
    replies = vm.get_roottable()["replies"]
    assert str(replies[len(replies) - 1]["status"]) == "INVALID_LOCATION"
    assert int(vm.get_roottable()["real_calls"]) == 0


def test_response_limit_correlation_and_duplicate_keys():
    _, before, _, _ = controlled_success(vm_for())
    raw = before.model_dump_json().encode()
    assert len(raw) <= 512
    with pytest.raises(ValueError):
        RoadReadback.parse_for(request(request_id="different"), raw)
    with pytest.raises(ValueError):
        RoadReadback.parse_for(request(), b" " * 513)
    with pytest.raises(ValueError):
        RoadReadback.parse_for(request(), raw[:-1] + b',"protocol":1}')


def test_separate_secure_mutation_policy_preserves_read_only_session():
    session = object.__new__(RoadSecureSession)
    session._state = AuthState.ACTIVE
    frame = encode_gamescript(request("build").to_bytes())
    session.validate_outbound(frame)
    with pytest.raises(ValueError):
        GameScriptSession.validate_outbound(session, frame)
    with pytest.raises(ValueError):
        session.validate_outbound(encode_gamescript(b'{"op":"terraform"}'))


def test_immutable_prelaunch_failure_does_not_launch(tmp_path, monkeypatch):
    prepared = prepare(tmp_path / "prelaunch")
    try:
        preflight(prepared)
        source = prepared.spec.workspace.game / "RoadMutationProof/main.nut"
        source.write_text(source.read_text() + "\n// changed\n")

        def forbidden(*args, **kwargs):
            pytest.fail("failed preflight attempted a native launch")

        monkeypatch.setattr("subprocess.Popen", forbidden)
        with pytest.raises(ValueError, match="Frozen"):
            asyncio.run(run(prepared))
        assert not (prepared.directory / "CLAIM.json").exists()
    finally:
        prepared.spec.workspace.close()


def retained_controlled_receipt(root):
    """Simulated artifact replay exercises verifier semantics, not native provenance."""
    (root / "PRELAUNCH.json").write_text("{}\n")
    (root / "before.sav").write_bytes(b"controlled before save")
    (root / "after.sav").write_bytes(b"controlled after save")
    seal = sha256(root / "PRELAUNCH.json")
    vm = vm_for()
    q = request(plan=seal)
    before = handle(vm, q)
    intent = admit_segment(
        before,
        prelaunch_digest=seal,
        source_save_digest=sha256(root / "before.sav"),
        max_cost=10000,
    )
    build = request("build", request_id="build-1", plan=intent.digest)
    read = request("read", request_id="read-1", plan=intent.digest)
    built, after = handle(vm, build), handle(vm, read)
    frames = []
    for query, response in ((q, before), (build, built), (read, after)):
        raw = response.model_dump_json().encode()
        (root / (query.request_id + "-request.json")).write_bytes(query.to_bytes())
        (root / (query.request_id + "-response.json")).write_bytes(raw)
        frames += [
            ("outbound", encode_gamescript(query.to_bytes()).hex()),
            ("inbound", encode_admin_frame(SERVER_GAMESCRIPT, raw + b"\0").hex()),
        ]
    receipt = verify_segment(intent, before, built, after)
    receipt.update(
        before_save_sha256=sha256(root / "before.sav"), after_save_sha256=sha256(root / "after.sav")
    )
    write_json(root / "receipt.json", receipt)
    write_json(root / "plan.json", intent.model_dump(mode="json"))
    write_json(root / "frames.json", frames)
    write_json(root / "runtime-identity.json", dict(encrypted=True, welcome=dict(revision="15.3")))
    write_json(
        root / "result.json", dict(native_launches=1, connections=1, status="NATIVE_STATE_VERIFIED")
    )
    write_json(
        root / "cleanup.json",
        dict(reaped=True, sockets_closed=True, workspace_disposed=True, credential_removed=True),
    )
    (root / "artifact-manifest.sha256").write_text(manifest(root))
    return receipt


def test_retained_receipt_semantic_replay(tmp_path):
    expected = retained_controlled_receipt(tmp_path)
    assert verify_receipt(tmp_path) == expected


@pytest.mark.parametrize("defect", ["save", "receipt", "frame", "connection", "cleanup"])
def test_retained_corruption_cannot_be_success(tmp_path, defect):
    retained_controlled_receipt(tmp_path)
    if defect == "save":
        (tmp_path / "before.sav").write_bytes(b"different source save")
    else:
        name = {
            "receipt": "receipt.json",
            "frame": "frames.json",
            "connection": "result.json",
            "cleanup": "cleanup.json",
        }[defect]
        path = tmp_path / name
        data = json.loads(path.read_bytes())
        if defect == "receipt":
            data["start"] += 1
        elif defect == "frame":
            data.pop()
        elif defect == "connection":
            data["connections"] = 2
        else:
            data["workspace_disposed"] = False
        path.write_text(json.dumps(data))
    # Even an updated transport manifest cannot hide a semantic mismatch.
    (tmp_path / "artifact-manifest.sha256").write_text(manifest(tmp_path))
    with pytest.raises(ValueError):
        verify_receipt(tmp_path)


def test_worst_case_response_remains_under_application_limit():
    _, before, _, _ = controlled_success(vm_for())
    worst = before.model_copy(
        update=dict(
            op="inspect",
            request_id="a" * 32,
            start=4095,
            end=4094,
            company=14,
            status="UNSUPPORTED_ROAD_TYPE",
            owner0=255,
            owner1=255,
            funds=-2147483648,
            cost=2147483647,
        )
    )
    assert len(json.dumps(worst.model_dump()).encode()) <= 512


def test_native_15_3_unowned_sentinel_is_admitted():
    # Captured inspect-9 in the single real attempt returned -1 for both vacant owners.
    # The version-15 GSCompany enum documents COMPANY_INVALID = -1.
    before = handle(vm_for(), request()).model_copy(update={"owner0": -1, "owner1": -1})
    intent = admit_segment(before, prelaunch_digest=SEAL, source_save_digest=SAVE, max_cost=10000)
    assert intent.start == before.start and intent.end == before.end
