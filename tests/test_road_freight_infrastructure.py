"""Controlled real Squirrel handler and receipt/one-shot runner contracts."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from squirrel import SQVM

from app.simulation.openttd.admin_protocol import ServerWelcome, encode_admin_frame
from app.simulation.openttd.gamescript_transport import SERVER_GAMESCRIPT, encode_gamescript
from app.simulation.openttd.proof import road_freight_infrastructure as proof
from app.simulation.openttd.proof.harness import manifest, sha256
from app.simulation.openttd.road_freight_infrastructure import (
    STAGES,
    FreightReadback,
    FreightRequest,
    admit_site,
    verify_construction,
)
from app.simulation.openttd.secure_admin import AuthState

SEAL = "a" * 64
SAVE = "b" * 64
PACKAGE = proof.road.PACKAGES / "road_freight_package"


def vm_for(
    *,
    funds=100000,
    invalid=False,
    vacant=True,
    reject=-1,
    mismatch=-1,
    changed=False,
    unavailable=False,
):
    vm = SQVM()
    vm.execute(Path("tests/fixtures/gamescript_api_15.nut").read_text())
    vm.execute(f"""
        ::funds <- {funds}; ::valid <- {str(not invalid).lower()};
        ::vacant <- {str(vacant).lower()}; ::reject <- {reject}; ::mismatch <- {mismatch};
        ::changed <- {str(changed).lower()}; ::available <- {str(not unavailable).lower()};
        ::road <- false; ::stop <- false; ::depot <- false;
        ::account <- 0; ::tests <- {{}}; ::real_calls <- 0; ::test_calls <- 0; ::cost <- 0;
        class GSCompany {{
            static COMPANY_INVALID=-1;
            static function ResolveCompanyID(c) {{ return ::valid && c==0 ? 0 : -1; }}
            static function GetBankBalance(c) {{ return ::funds; }}
        }}
        class GSCompanyMode {{ constructor(c) {{}} static function IsValid() {{return ::valid;}} }}
        class GSAccounting {{
            constructor() {{ ::account++; ::cost=0; }}
            function GetCosts() {{ return ::cost; }}
        }}
        class GSTestMode {{constructor() {{::tests[::account] <- true;}}}}
        class GSMap {{static function IsValidTile(t) {{return t>=0 && t<4096;}}}}
        class GSTile {{
            static TRANSPORT_ROAD=0; static TRANSPORT_RAIL=1;
            static TRANSPORT_WATER=2; static TRANSPORT_AIR=3;
            static function GetOwner(t) {{
                return (t==515 ? ::stop : (t==518 ? ::depot : ::road)) ? 0 : -1;
            }}
            static function IsBuildable(t) {{return ::vacant && GetOwner(t)==-1;}}
            static function GetSlope(t) {{return 0;}}
            static function GetMinHeight(t) {{return 1;}}
            static function IsWaterTile(t) {{return false;}}
            static function IsCoastTile(t) {{return false;}}
            static function HasTreeOnTile(t) {{return false;}}
            static function IsFarmTile(t) {{return false;}}
            static function IsRockTile(t) {{return false;}}
            static function IsRoughTile(t) {{return false;}}
            static function HasTransportType(t,k) {{return k==0 && GetOwner(t)==0;}}
        }}
        class GSStation {{
            static STATION_NEW=65535; static STATION_TRUCK_STOP=2; static STATION_BUS_STOP=4;
            static function GetStationID(t) {{return ::stop ? 7 : -1;}}
            static function IsValidStation(s) {{return ::stop && s==7;}}
            static function HasStationType(s,k) {{return ::stop && k==2;}}
        }}
        class GSRoad {{
            static ROADTYPE_ROAD=0; static ROADVEHTYPE_TRUCK=1;
            static function SetCurrentRoadType(t) {{if(t!=0) throw "type";}}
            static function GetCurrentRoadType() {{return 0;}}
            static function IsRoadTypeAvailable(t) {{return ::available;}}
            static function IsRoadTile(t) {{return ::road && (t==516 || t==517);}}
            static function IsRoadStationTile(t) {{return ::stop && t==515;}}
            static function IsDriveThroughRoadStationTile(t) {{return false;}}
            static function IsRoadDepotTile(t) {{return ::depot && t==518;}}
            static function GetRoadStationFrontTile(t) {{return ::mismatch==1 ? 514 : 516;}}
            static function GetRoadDepotFrontTile(t) {{return ::mismatch==2 ? 519 : 517;}}
            static function AreRoadTilesConnected(a,b) {{
                local lo=a<b?a:b; local hi=a>b?a:b;
                return ::road && ((lo==516 && hi==517) ||
                    (lo==515 && hi==516 && ::stop) || (lo==517 && hi==518 && ::depot));
            }}
            static function Do(i) {{
                ::cost=[40,60,80][i];
                if(::account in ::tests) {{
                    ::test_calls++;
                    if(::changed && ::test_calls>3) ::cost++;
                    return true;
                }}
                ::real_calls++;
                if(::reject==i) {{::cost=0;return false;}}
                ::funds-=::cost;
                if(i==0) ::road=(::mismatch!=0);
                if(i==1) ::stop=true;
                if(i==2) ::depot=true;
                return true;
            }}
            static function BuildRoadFull(a,b) {{
                if(a!=516 || b!=517) throw "geometry"; return Do(0);
            }}
            static function BuildRoadStation(t,f,k,s) {{
                if(t!=515 || f!=516 || k!=1 || s!=65535) throw "station"; return Do(1);
            }}
            static function BuildRoadDepot(t,f) {{
                if(t!=518 || f!=517) throw "depot"; return Do(2);
            }}
        }}
    """)
    vm.execute((PACKAGE / "main.nut").read_text())
    vm.execute("::bridge <- RoadFreightProof();")
    return vm


def request(op="inspect", **changes):
    d = dict(op=op, request_id=op + "-1", plan=SEAL, company=0, start=516, end=517, max_cost=10000)
    d.update(changes)
    return FreightRequest.model_validate(d)


def handle(vm, q):
    vm.execute("bridge.Handle(" + q.to_bytes().decode() + ");")
    replies = vm.get_roottable()["replies"]
    value = replies[len(replies) - 1]
    d = {}
    for k in value.keys():
        name = str(k)
        v = value[name]
        if name in ("op", "request_id", "plan", "status"):
            d[name] = str(v)
        elif name in ("road", "links"):
            d[name] = [bool(v[i]) for i in range(len(v))]
        elif name in ("owners", "fronts", "costs"):
            d[name] = [int(v[i]) for i in range(len(v))]
        elif name in ("stop", "truck", "depot", "eligible"):
            d[name] = bool(v)
        else:
            d[name] = int(v)
    return FreightReadback.parse_for(q, json.dumps(d, separators=(",", ":")).encode())


def success():
    vm = vm_for()
    before = handle(vm, request())
    plan = admit_site(before, prelaunch_digest=SEAL, source_save_digest=SAVE, max_cost=10000)
    pairs = []
    for stage in STAGES:
        built = handle(vm, request(stage, plan=plan.digest))
        after = handle(vm, request("read", request_id="read-" + stage, plan=plan.digest))
        pairs.append((built, after))
    return vm, plan, before, pairs


def test_actual_handler_three_owned_constructions_and_receipt():
    vm, plan, before, pairs = success()
    receipt = verify_construction(plan, before, pairs)
    assert receipt["tiles"] == [515, 516, 517, 518]
    assert receipt["spent"] == 180 and receipt["station_id"] == 7
    assert pairs[-1][1].funds == 99820
    assert int(vm.get_roottable()["real_calls"]) == 3
    again = handle(vm, request("depot", request_id="again", plan=plan.digest))
    assert again.status == "OUT_OF_ORDER"
    assert int(vm.get_roottable()["real_calls"]) == 3


@pytest.mark.parametrize(
    "kwargs,status",
    [
        ({"invalid": True}, "INVALID_COMPANY"),
        ({"funds": 179}, "INSUFFICIENT_FUNDS"),
        ({"vacant": False}, "NOT_BUILDABLE"),
        ({"unavailable": True}, "UNSUPPORTED_ROAD_TYPE"),
    ],
)
def test_rejected_admission_has_zero_real_commands(kwargs, status):
    vm = vm_for(**kwargs)
    before = handle(vm, request())
    assert before.status == status
    with pytest.raises(ValueError):
        admit_site(before, prelaunch_digest=SEAL, source_save_digest=SAVE, max_cost=10000)
    assert int(vm.get_roottable()["real_calls"]) == 0


@pytest.mark.parametrize("stage", range(3))
@pytest.mark.parametrize("kind", ["reject", "mismatch"])
def test_failed_command_or_state_latches_and_stops(stage, kind):
    vm = vm_for(**{kind: stage})
    before = handle(vm, request())
    plan = admit_site(before, prelaunch_digest=SEAL, source_save_digest=SAVE, max_cost=10000)
    for i in range(stage + 1):
        result = handle(vm, request(STAGES[i], plan=plan.digest))
    assert result.status == ("REJECTED" if kind == "reject" else "READBACK_MISMATCH")
    again = handle(vm, request(STAGES[stage], request_id="retry", plan=plan.digest))
    assert again.status == "OUT_OF_ORDER"
    assert int(vm.get_roottable()["real_calls"]) == stage + 1


def test_native_cost_change_rejects_before_first_real_command():
    vm = vm_for(changed=True)
    before = handle(vm, request())
    assert before.status == "READY"
    assert handle(vm, request("road")).status == "COST_CHANGED"
    assert int(vm.get_roottable()["real_calls"]) == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("owners", (0, 0, 0, 1)),
        ("links", (True, True, False)),
        ("fronts", (516, 519)),
        ("truck", False),
        ("funds", 99821),
        ("sid", 8),
    ],
)
def test_independent_readback_corruption_cannot_be_receipt(field, value):
    _, plan, before, pairs = success()
    pairs[-1] = (pairs[-1][0], pairs[-1][1].model_copy(update={field: value}))
    with pytest.raises(ValueError):
        verify_construction(plan, before, pairs)


def test_bad_layout_and_total_budget_rejected():
    with pytest.raises(ValueError):
        request(start=63, end=64).to_bytes()
    vm = vm_for()
    before = handle(vm, request(max_cost=179))
    assert before.status == "COST_LIMIT"
    assert int(vm.get_roottable()["real_calls"]) == 0


def test_response_size_bound():
    _, _, before, _ = success()
    worst = before.model_copy(
        update=dict(
            request_id="a" * 32,
            status="INSUFFICIENT_FUNDS",
            company=14,
            start=4093,
            end=4094,
            owners=(255, 255, 255, 255),
            fronts=(4093, 4094),
            sid=65535,
            funds=-2147483648,
            cost=2147483647,
            costs=(2147483647,) * 3,
        )
    )
    assert len(json.dumps(worst.model_dump(), separators=(",", ":")).encode()) <= 512


def test_stale_packaged_source_blocks_without_launch(tmp_path, monkeypatch):
    prepared = proof.prepare(tmp_path / "sealed")
    try:
        proof.preflight(prepared)
        staged = prepared.spec.workspace.game / "RoadFreightProof/main.nut"
        assert staged.read_bytes() == (PACKAGE / "main.nut").read_bytes()
        staged.write_text(staged.read_text() + "\n// stale\n")
        monkeypatch.setattr("subprocess.Popen", lambda *a, **k: pytest.fail("native launch"))
        with pytest.raises(ValueError, match="Frozen"):
            asyncio.run(proof.run(prepared))
        assert not (prepared.directory / "CLAIM.json").exists()
    finally:
        prepared.spec.workspace.close()


async def noop(*args, **kwargs):
    return None


def controlled_run(tmp_path, monkeypatch, *, reject=-1, corrupt_read=False):
    """Simulated runtime lifecycle; never evidence of a native launch."""
    prepared = proof.prepare(tmp_path / "controlled")
    vm = vm_for(reject=reject)
    session = SimpleNamespace(
        state=AuthState.ACTIVE,
        protocol=object(),
        welcome=ServerWelcome("controlled", "15.3", True, "simulated", 42, 0, 0, 64, 64),
        authenticate=noop,
    )
    lifecycle = {"launches": 0, "connections": 0, "cleanup": 0}

    class Backend:
        def __init__(self, **kwargs):
            self.process = SimpleNamespace(pid=123)
            self.session = None

        def preflight(self, prepared):
            pass

        async def launch(self, prepared):
            lifecycle["launches"] += 1

        async def cleanup(self, prepared):
            lifecycle["cleanup"] += 1
            return dict(reaped=True, sockets_closed=True, cleanup_error=[], remaining_processes=[])

    async def connect(*args, **kwargs):
        lifecycle["connections"] += 1
        session.observer = kwargs["frame_observer"]
        return session

    async def save(backend, prepared, name):
        path = prepared.directory / (name + ".sav")
        path.write_bytes(b"simulated save " + name.encode())
        return sha256(path)

    async def exchange(session, q, directory):
        value = handle(vm, q)
        if corrupt_read and q.request_id == "read-road":
            value = value.model_copy(update={"links": (False, False, False)})
        raw = value.model_dump_json().encode()
        (directory / (q.request_id + "-request.json")).write_bytes(q.to_bytes())
        (directory / (q.request_id + "-response.json")).write_bytes(raw)
        session.observer("outbound", encode_gamescript(q.to_bytes()))
        session.observer("inbound", encode_admin_frame(SERVER_GAMESCRIPT, raw + b"\0"))
        return value

    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: pytest.fail("real process prohibited"))
    monkeypatch.setattr(proof, "NativeBackend", Backend)
    monkeypatch.setattr(proof.FreightSecureSession, "connect_secure", connect)
    monkeypatch.setattr(proof, "GameScriptTransport", lambda *a: SimpleNamespace(subscribe=noop))
    monkeypatch.setattr(proof, "wait_log", noop)
    monkeypatch.setattr(proof, "console", lambda *a: None)
    monkeypatch.setattr(proof, "save", save)
    monkeypatch.setattr(proof, "exchange", exchange)
    monkeypatch.setattr(
        proof,
        "kernel_socket_rows",
        lambda: [dict(table="tcp", local_port=prepared.endpoints[1], state=10)],
    )
    monkeypatch.setattr(proof, "verify_cleanup_endpoints", lambda *a: {})
    result = asyncio.run(proof.run(prepared))
    return prepared, result, lifecycle


def test_controlled_runner_and_retained_receipt_replay(tmp_path, monkeypatch):
    prepared, result, lifecycle = controlled_run(tmp_path, monkeypatch)
    root = prepared.directory
    assert result["status"] == "NATIVE_STATE_VERIFIED"
    assert result["build_requests"] == 3 and result["requests"] == 7
    assert lifecycle == dict(launches=1, connections=1, cleanup=1)
    assert proof.verify_receipt(root)["spent"] == 180
    with pytest.raises(ValueError, match="already consumed"):
        # Reopening is unnecessary: the immutable CLAIM prevents a second attempt.
        proof.road.preflight(prepared)


@pytest.mark.parametrize("kwargs,builds", [({"reject": 1}, 2), ({"corrupt_read": True}, 1)])
def test_runner_stops_without_next_build_or_receipt(tmp_path, monkeypatch, kwargs, builds):
    prepared, result, lifecycle = controlled_run(tmp_path, monkeypatch, **kwargs)
    root = prepared.directory
    assert result["status"] == "FAILED" and result["build_requests"] == builds
    assert not (root / "receipt.json").exists()
    assert lifecycle == dict(launches=1, connections=1, cleanup=1)
    assert json.loads((root / "cleanup.json").read_text())["workspace_disposed"] is True


@pytest.mark.parametrize("defect", ["frame", "plan", "receipt", "save", "cleanup"])
def test_retained_receipt_corruption_rejected_even_with_new_manifest(tmp_path, monkeypatch, defect):
    prepared, _, _ = controlled_run(tmp_path, monkeypatch)
    root = prepared.directory
    path = (
        root
        / {
            "frame": "frames.json",
            "plan": "plan.json",
            "receipt": "receipt.json",
            "save": "after.sav",
            "cleanup": "cleanup.json",
        }[defect]
    )
    if defect == "save":
        path.write_bytes(b"corrupt save")
    else:
        d = json.loads(path.read_text())
        if defect == "frame":
            d.pop()
        elif defect == "plan":
            d["start"] += 1
        elif defect == "receipt":
            d["spent"] += 1
        else:
            d["sockets_closed"] = False
        path.write_text(json.dumps(d))
    (root / "artifact-manifest.sha256").write_text(manifest(root))
    with pytest.raises((ValueError, KeyError)):
        proof.verify_receipt(root)


def test_secure_policy_rejects_unsupported_action():
    session = object.__new__(proof.FreightSecureSession)
    session._state = AuthState.ACTIVE
    session.validate_outbound(encode_gamescript(request("stop").to_bytes()))
    with pytest.raises(ValueError):
        session.validate_outbound(encode_gamescript(b'{"op":"buy-vehicle"}'))
    with pytest.raises(ValueError):
        session.validate_outbound(
            encode_gamescript(request(start=63, end=64).model_dump_json().encode())
        )


def test_package_registration_and_wire_duplicates():
    vm = SQVM()
    vm.execute(
        'class GSInfo {} function RegisterGS(v) { if(v.GetAPIVersion()!="15" || '
        'v.CreateInstance()!="RoadFreightProof") throw "registration"; }'
    )
    vm.execute((PACKAGE / "info.nut").read_text())
    _, _, before, _ = success()
    raw = before.model_dump_json().encode()
    with pytest.raises(ValueError, match="duplicate"):
        FreightReadback.parse_for(request(), raw[:-1] + b',"cost":0}')
    with pytest.raises(ValueError, match="correlation"):
        FreightReadback.parse_for(request(plan="c" * 64), raw)
