"""Controlled Squirrel lifecycle tests; simulated results are not native proof."""

import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from squirrel import SQVM

from app.simulation.openttd.admin_protocol import ServerWelcome, encode_admin_frame
from app.simulation.openttd.gamescript_transport import SERVER_GAMESCRIPT, encode_gamescript
from app.simulation.openttd.proof import road_vehicle_lifecycle as proof
from app.simulation.openttd.proof.harness import manifest, sha256
from app.simulation.openttd.road_vehicle_lifecycle import (
    MOTION_POLLS,
    MOTION_TICKS,
    VehicleMotionReadback,
    VehicleReadback,
    VehicleRequest,
    admit_engine,
    verify_lifecycle,
)
from app.simulation.openttd.secure_admin import AuthState

SEAL = "a" * 64
SAVE = "b" * 64
SITE = "c" * 64
RECEIPT = "d" * 64


def vm_for(
    *,
    unavailable=False,
    funds=98989,
    invalid_depot=False,
    invalid_company=False,
    fail_purchase=False,
    fail_order=False,
    fail_order_test=False,
    mismatch=False,
    cost_changed=False,
    no_movement=False,
    departure_tick=0,
    paused=False,
    frozen_clock=False,
    invalid_route=False,
):
    vm = SQVM()
    vm.execute(Path("tests/fixtures/gamescript_api_15.nut").read_text())
    vm.execute(f"""
        ::funds <- {funds}; ::available <- {str(not unavailable).lower()};
        ::site_valid <- {str(not invalid_depot).lower()};
        ::company_valid <- {str(not invalid_company).lower()};
        ::fail_purchase <- {str(fail_purchase).lower()}; ::fail_order <- {str(fail_order).lower()};
        ::fail_order_test <- {str(fail_order_test).lower()}; ::mismatch <- {str(mismatch).lower()};
        ::cost_changed <- {str(cost_changed).lower()}; ::no_movement <- {str(no_movement).lower()};
        ::vehicle <- false; ::running <- false; ::orders <- 0;
        ::departure_tick <- {departure_tick}; ::paused <- {str(paused).lower()};
        ::frozen_clock <- {str(frozen_clock).lower()};
        ::invalid_route <- {str(invalid_route).lower()};
        class GSGame {{static function IsPaused() {{return ::paused;}}}}
        ::GSController = class {{
            static function GetTick() {{return ::ticks;}}
            function Sleep(n) {{if(!::frozen_clock) ::ticks+=n;}}
        }};
        ::account <- 0;
        ::tests <- {{}};
        ::cost <- 0;
        ::purchases <- 0;
        ::order_calls <- 0;
        ::starts <- 0;
        ::purchase_tests <- 0;
        class GSCompany {{
            static COMPANY_INVALID=-1;
            static function ResolveCompanyID(c) {{return ::company_valid && c==0 ? 0 : -1;}}
            static function GetBankBalance(c) {{return ::funds;}}
        }}
        class GSCompanyMode {{constructor(c) {{}}
            static function IsValid() {{return ::company_valid;}}}}
        class GSAccounting {{
            constructor() {{::account++;::cost=0;}}
            function GetCosts() {{return ::cost;}}
        }}
        class GSTestMode {{constructor() {{::tests[::account] <- true;}}}}
        class GSMap {{static function IsValidTile(t) {{return t>=0 && t<4096;}}}}
        class GSTile {{
            static TRANSPORT_ROAD=0;static TRANSPORT_RAIL=1;
            static TRANSPORT_WATER=2;static TRANSPORT_AIR=3;
            static function GetOwner(t) {{return 0;}}
            static function IsBuildable(t) {{return false;}}
            static function GetSlope(t) {{return 0;}}
            static function GetMinHeight(t) {{return 1;}}
           
            static function IsWaterTile(t) {{return false;}}
            static function IsCoastTile(t) {{return false;}}
           
            static function HasTreeOnTile(t) {{return false;}}
            static function IsFarmTile(t) {{return false;}}
           
            static function IsRockTile(t) {{return false;}}
            static function IsRoughTile(t) {{return false;}}
            static function HasTransportType(t,k) {{return k==0;}}
        }}
        class GSRoad {{
            static ROADTYPE_ROAD=0;static ROADVEHTYPE_TRUCK=1;
           
            static function SetCurrentRoadType(t) {{}}
            static function GetCurrentRoadType() {{return 0;}}
            static function IsRoadTypeAvailable(t) {{return true;}}
            static function IsRoadTile(t) {{return t==1292 || t==1293;}}
            static function IsRoadStationTile(t) {{return t==1291;}}
            static function IsDriveThroughRoadStationTile(t) {{return false;}}
            static function IsRoadDepotTile(t) {{return ::site_valid && t==1294;}}
            static function GetRoadDepotFrontTile(t) {{return 1293;}}
            static function GetRoadStationFrontTile(t) {{return 1292;}}
            static function GetRoadVehicleTypeForCargo(c) {{return 1;}}
            static function AreRoadTilesConnected(a,b) {{return !::invalid_route && abs(a-b)==1;}}
        }}
        class GSStation {{
            static STATION_TRUCK_STOP=2;static STATION_BUS_STOP=4;
           
            static function GetStationID(t) {{return 0;}}
            static function IsValidStation(s) {{return s==0;}}
            static function HasStationType(s,k) {{return k==2;}}
        }}
        class GSCargo {{static function IsValidCargo(c) {{return c==3;}}}}
        class GSEngine {{
            static function IsBuildable(e) {{return ::available && (e==42 || e==43);}}
            static function IsValidEngine(e) {{return IsBuildable(e);}}
           
            static function GetVehicleType(e) {{return 1;}}
            static function IsArticulated(e) {{return false;}}
           
            static function CanRunOnRoad(e,t) {{return true;}}
            static function HasPowerOnRoad(e,t) {{return true;}}
           
            static function GetCargoType(e) {{return 3;}}
            static function CanRefitCargo(e,c) {{return c==3;}}
           
            static function GetCapacity(e) {{return 20;}}
            static function GetPrice(e) {{return 5000;}}
        }}
        class GSEngineList {{
            i=0; constructor(k) {{}} function Begin() {{i=0;return 43;}}
            function Next() {{i++;return 42;}} function IsEnd() {{return i>=2;}}
        }}
        class GSVehicleList {{function Count() {{return ::vehicle ? 1 : 0;}}}}
        class GSVehicle {{
            static VT_ROAD=1;static VS_RUNNING=0;static VS_STOPPED=1;static VS_IN_DEPOT=2;
            static VS_AT_STATION=3;static VS_BROKEN=4;static VS_CRASHED=5;
            static function IsValidVehicle(v) {{return ::vehicle && v==23;}}
            static function IsPrimaryVehicle(v) {{return IsValidVehicle(v);}}
           
            static function GetEngineType(v) {{return 42;}}
            static function GetOwner(v) {{return ::mismatch ? 1 : 0;}}
            static function GetCapacity(v,c) {{return c==3 ? 20 : 0;}}
            static function GetLocation(v) {{return ::running && !::no_movement &&
                ::ticks>=::departure_tick ? 1293 : 1294;}}
           
            static function IsInDepot(v) {{return !::running;}}
            static function GetCurrentSpeed(v) {{return ::running ? 10 : 0;}}
            static function GetState(v) {{return ::running ? 0 : 2;}}
            static function BuildVehicle(d,e) {{
                if(d!=1294 || e!=42) throw "purchase geometry";
                ::cost=5000;
                if(::account in ::tests) {{
                    ::purchase_tests++;
                    if(::cost_changed && ::purchase_tests>1) ::cost++;
                    return 0;
                }}
                ::purchases++;if(::fail_purchase) {{::cost=0;return 65535;}}
                ::vehicle=true;::funds-=5000;return 23;
            }}
            static function StartStopVehicle(v) {{
                ::cost=0;if(::account in ::tests) return true;
                ::starts++;::running=!::running;return true;
            }}
        }}
        class GSOrder {{
            static OF_NONE=0;
            static function AreOrderFlagsValid(t,f) {{return t==1291 && f==0;}}
            static function GetOrderCount(v) {{return ::orders;}}
            static function GetOrderDestination(v,n) {{return 1291;}}
            static function GetOrderFlags(v,n) {{return 0;}}
            static function IsGotoStationOrder(v,n) {{return ::orders==1;}}
            static function AppendOrder(v,t,f) {{
                ::cost=0;if(::account in ::tests) return !::fail_order_test;
                ::order_calls++;if(::fail_order) return false;
                ::orders++;return true;
            }}
        }}
    """)
    vm.execute((proof.PACKAGE / "infrastructure.nut").read_text())
    vm.execute(
        (proof.PACKAGE / "main.nut").read_text().replace('require("infrastructure.nut");', "")
    )
    vm.execute("::bridge <- RoadVehicleProof();")
    return vm


def request(op="engine", **changes):
    d = dict(
        op=op, request_id=op + "-1", plan=SEAL, company=0, depot=1294, stop=1291, max_cost=20000
    )
    d.update(changes)
    return VehicleRequest.model_validate(d)


def handle(vm, q):
    vm.execute("bridge.Handle(" + q.to_bytes().decode() + ");")
    replies = vm.get_roottable()["replies"]
    table = replies[len(replies) - 1]
    d = {}
    for key in table.keys():
        k = str(key)
        v = table[k]
        if k in ("op", "request_id", "plan", "status", "state"):
            d[k] = str(v)
        elif k in ("available", "compatible", "indepot"):
            d[k] = bool(v)
        elif k == "order":
            d[k] = [int(v[0]), int(v[1]), int(v[2]), bool(v[3])]
        elif k == "clock":
            d[k] = [int(v[0]), int(v[1]), int(v[2]), bool(v[3])]
        elif k == "v":
            d[k] = [
                str(v[i])
                if i == 11
                else [int(v[i][0]), int(v[i][1]), int(v[i][2]), bool(v[i][3])]
                if i == 14
                else bool(v[i])
                if i in (3, 4, 12)
                else int(v[i])
                for i in range(15)
            ]
        else:
            d[k] = int(v)
    return VehicleReadback.parse_for(q, json.dumps(d, separators=(",", ":")).encode())


def admit(vm):
    engine = handle(vm, request())
    plan = admit_engine(
        engine,
        prelaunch_digest=SEAL,
        infrastructure_receipt_digest=RECEIPT,
        source_save_digest=SAVE,
        site_digest=SITE,
        max_cost=20000,
    )
    return engine, plan


def sequence(vm, before_motion=None):
    engine, plan = admit(vm)
    records = {}
    vid = -1
    for op, identifier in [
        ("purchase", "purchase-1"),
        ("vread", "read-purchase"),
        ("order-check", "order-check-1"),
        ("order", "order-1"),
        ("vread", "read-order"),
        ("start-check", "start-check-1"),
        ("start", "start-1"),
        ("vread", "read-start"),
        ("motion", "motion-1"),
    ]:
        if op == "motion" and before_motion is not None:
            before_motion(vm)
        r = handle(
            vm,
            request(
                op,
                request_id=identifier,
                plan=plan.digest,
                engine=plan.engine,
                cargo=plan.cargo,
                vehicle=vid,
                expected_cost=plan.purchase_cost,
            ),
        )
        records[identifier] = r
        if op == "purchase":
            vid = r.vehicle
    return engine, plan, records


def test_actual_handler_purchase_order_start_and_readback_receipt():
    vm = vm_for()
    engine, plan, records = sequence(vm)
    receipt = verify_lifecycle(plan, engine, records)
    assert plan.engine == 42 and plan.cargo == 3 and plan.capacity == 20
    assert receipt["vehicle"] == 23 and receipt["purchase_cost"] == 5000
    assert receipt["locations"] == [1294, 1293, 1293]
    assert receipt["freight_delivery_proven"] is False
    root = vm.get_roottable()
    assert [int(root[k]) for k in ("purchases", "order_calls", "starts")] == [1, 1, 1]
    replies = root["replies"]
    count = len(replies)
    q = request(
        "start",
        request_id="again",
        plan=plan.digest,
        engine=42,
        cargo=3,
        vehicle=23,
        expected_cost=5000,
    )
    vm.execute("bridge.Handle(" + q.to_bytes().decode() + ");")
    assert len(replies) == count and int(root["starts"]) == 1


def test_delayed_departure_requires_observed_tile_transition():
    vm = vm_for(departure_tick=80)
    engine, plan, records = sequence(vm)
    assert records["read-start"].location == 1294
    assert records["motion-1"].status == "MOVED"
    assert records["motion-1"].location == 1293
    assert verify_lifecycle(plan, engine, records)["locations"] == [1294, 1294, 1293]
    assert records["motion-1"].clock == (0, 80, 81, False)


@pytest.mark.parametrize(
    "kwargs,status,clock",
    [
        ({"no_movement": True}, "WINDOW_EXHAUSTED", (0, MOTION_TICKS, MOTION_POLLS, False)),
        ({"paused": True}, "PAUSED", (0, 0, 1, True)),
        ({"frozen_clock": True, "departure_tick": 80}, "CLOCK_STALLED", (0, 0, 2, False)),
        (
            {"departure_tick": MOTION_TICKS + 1},
            "WINDOW_EXHAUSTED",
            (0, MOTION_TICKS, MOTION_POLLS, False),
        ),
    ],
)
def test_motion_failure_is_bounded_and_never_becomes_success(kwargs, status, clock):
    vm = vm_for(**kwargs)
    engine, plan, records = sequence(vm)
    motion = records["motion-1"]
    assert motion.status == status and motion.clock == clock
    with pytest.raises(ValueError, match="movement mismatch"):
        verify_lifecycle(plan, engine, records)
    assert int(vm.get_roottable()["starts"]) == 1


def test_invalid_route_is_distinct_from_observation_exhaustion():
    vm = vm_for(departure_tick=80)
    engine, plan, records = sequence(vm, lambda v: v.execute("::orders=0;"))
    assert records["motion-1"].status == "INVALID_ROUTE"
    assert records["motion-1"].clock == (0, 0, 1, False)
    with pytest.raises(ValueError):
        verify_lifecycle(plan, engine, records)


def test_lost_road_connection_blocks_motion_admission():
    engine, plan, records = sequence(
        vm_for(departure_tick=80), lambda v: v.execute("::invalid_route=true;")
    )
    assert records["motion-1"].status == "INVALID_ROUTE"
    with pytest.raises(ValueError):
        verify_lifecycle(plan, engine, records)


def test_historical_speed_does_not_satisfy_corrected_movement_gate():
    historical = Path("artifacts/runtime/openttd-15.3-road-vehicle-lifecycle-attempt1")
    raw = (historical / "motion-1-response.json").read_bytes()
    q = VehicleRequest.model_validate_json((historical / "motion-1-request.json").read_bytes())
    r = VehicleReadback.parse_for(q, raw)
    assert r.status == "NO_MOVEMENT" and r.location == 1294 and r.speed == 30
    assert not isinstance(r, VehicleMotionReadback)


def test_attempt_two_predecessor_requires_immutable_failure_and_cleanup(tmp_path):
    identity = proof.previous_identity()
    assert (
        identity["prelaunch_sha256"]
        == "2eff9d6c48c1eaf136529408ab58ce785aa81191ff2c4a6125c389f9c11b2328"
    )
    copied = tmp_path / "predecessor"
    copied.mkdir()
    for path in proof.PREVIOUS.iterdir():
        if path.is_file():
            shutil.copyfile(path, copied / path.name)
    cleanup = json.loads((copied / "cleanup.json").read_text())
    cleanup["credential_removed"] = False
    (copied / "cleanup.json").write_text(json.dumps(cleanup))
    (copied / "artifact-manifest.sha256").write_text(manifest(copied))
    with pytest.raises(ValueError, match="predecessor"):
        proof.previous_identity(copied)


def test_movement_at_exact_bound_is_admitted_but_clock_jump_is_not():
    engine, plan, records = sequence(vm_for(departure_tick=MOTION_TICKS))
    assert records["motion-1"].clock == (0, MOTION_TICKS, MOTION_POLLS, False)
    verify_lifecycle(plan, engine, records)
    records["motion-1"] = records["motion-1"].model_copy(
        update={"clock": (0, MOTION_TICKS + 1, 2, False)}
    )
    with pytest.raises(ValueError, match="clock"):
        verify_lifecycle(plan, engine, records)


def test_motion_response_maximum_size_and_clock_identity():
    _, _, records = sequence(vm_for())
    motion = records["motion-1"]
    worst = motion.model_copy(
        update=dict(
            request_id="a" * 32,
            engine=65535,
            cargo=65535,
            vehicle=65535,
            capacity=2147483647,
            price=2147483647,
            cost=2147483647,
            funds=-2147483648,
            speed=2147483647,
            order=(65535, 4095, 65535, False),
            state="AT_STATION",
            status="READBACK_MISMATCH",
            clock=(2147483391, 2147483647, 257, False),
        )
    )
    raw = worst.to_bytes()
    assert len(raw) <= 512
    q = request(
        "motion",
        request_id=worst.request_id,
        plan=worst.plan,
        engine=65535,
        cargo=65535,
        vehicle=65535,
        expected_cost=5000,
    )
    assert VehicleReadback.parse_for(q, raw) == worst
    with pytest.raises(ValueError, match="duplicate"):
        VehicleReadback.parse_for(q, raw[:-1] + b',"clock":[0,1,2,false]}')
    assert isinstance(motion, VehicleMotionReadback)


def test_wall_deadline_has_explicit_failure_and_no_retry(tmp_path, monkeypatch):
    sent = []

    async def send(value):
        sent.append(value)

    async def receive():
        await asyncio.Event().wait()

    monkeypatch.setattr(proof, "MOTION_SECONDS", 0.01)
    session = SimpleNamespace(send=send, receive=receive)
    with pytest.raises(TimeoutError, match="MOVEMENT_WALL_DEADLINE_EXPIRED"):
        asyncio.run(proof.exchange(session, request("motion"), tmp_path))
    assert len(sent) == 1 and not (tmp_path / "engine-1-response.json").exists()


@pytest.mark.parametrize(
    "kwargs,status",
    [
        ({"unavailable": True}, "NO_ENGINE"),
        ({"funds": 4999}, "INSUFFICIENT_FUNDS"),
        ({"invalid_depot": True}, "INVALID_SITE"),
        ({"invalid_company": True}, "INVALID_COMPANY"),
    ],
)
def test_invalid_engine_funds_company_or_depot_cannot_purchase(kwargs, status):
    vm = vm_for(**kwargs)
    engine = handle(vm, request())
    assert engine.status == status
    with pytest.raises(ValueError):
        admit_engine(
            engine,
            prelaunch_digest=SEAL,
            infrastructure_receipt_digest=RECEIPT,
            source_save_digest=SAVE,
            site_digest=SITE,
            max_cost=20000,
        )
    assert int(vm.get_roottable()["purchases"]) == 0


@pytest.mark.parametrize(
    "kwargs,status",
    [
        ({"fail_purchase": True}, "REJECTED"),
        ({"mismatch": True}, "READBACK_MISMATCH"),
        ({"cost_changed": True}, "COST_CHANGED"),
    ],
)
def test_purchase_failure_latches_without_another_purchase(kwargs, status):
    vm = vm_for(**kwargs)
    _, plan = admit(vm)
    q = request("purchase", plan=plan.digest, engine=42, cargo=3, expected_cost=5000)
    r = handle(vm, q)
    assert r.status == status
    again = handle(vm, q.model_copy(update={"request_id": "purchase-again"}))
    assert again.status == "OUT_OF_ORDER"
    assert int(vm.get_roottable()["purchases"]) == (0 if "cost_changed" in kwargs else 1)


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner", 1),
        ("capacity", 19),
        ("order", (2, 1291, 0, True)),
        ("engine", 43),
        ("location", 1294),
        ("state", "STOPPED"),
    ],
)
def test_corrupt_independent_native_readback_cannot_be_receipt(field, value):
    engine, plan, records = sequence(vm_for())
    records["motion-1"] = records["motion-1"].model_copy(update={field: value})
    with pytest.raises(ValueError):
        verify_lifecycle(plan, engine, records)


def test_response_size_and_wire_identity():
    engine, _, _ = sequence(vm_for())
    worst = engine.model_copy(
        update=dict(
            op="start-check",
            request_id="a" * 32,
            company=14,
            depot=4095,
            stop=4092,
            engine=65535,
            cargo=65535,
            vehicle=65535,
            capacity=2147483647,
            price=2147483647,
            cost=2147483647,
            funds=-2147483648,
            owner=255,
            location=4095,
            state="AT_STATION",
            speed=2147483647,
            order=(65535, 4095, 65535, False),
            status="INSUFFICIENT_FUNDS",
        )
    )
    assert len(worst.model_dump_json().encode()) <= 512
    raw = engine.model_dump_json().encode()
    with pytest.raises(ValueError, match="duplicate"):
        VehicleReadback.parse_for(request(), raw[:-1] + b',"cost":0}')
    with pytest.raises(ValueError, match="correlation"):
        VehicleReadback.parse_for(request(plan="e" * 64), raw)


def test_stale_source_save_or_package_prevents_native_launch(tmp_path, monkeypatch):
    prepared = proof.prepare(tmp_path / "prepared")
    try:
        proof.preflight(prepared)
        target = prepared.spec.workspace.game / "RoadFreightProof/main.nut"
        target.write_text(target.read_text() + "\n// stale\n")
        monkeypatch.setattr(
            "subprocess.Popen", lambda *a, **k: pytest.fail("native launch prohibited")
        )
        with pytest.raises(ValueError, match="Frozen"):
            asyncio.run(proof.run(prepared))
        assert not (prepared.directory / "CLAIM.json").exists()
    finally:
        prepared.spec.workspace.close()


async def noop(*args, **kwargs):
    return None


def controlled_run(
    tmp_path,
    monkeypatch,
    *,
    fail_order=False,
    fail_order_test=False,
    unavailable=False,
    corrupt_read=False,
    invalid_depot=False,
):
    """Simulated launch and encrypted-frame records, never native evidence."""
    prepared = proof.prepare(tmp_path / "controlled")
    vm = vm_for(
        fail_order=fail_order,
        fail_order_test=fail_order_test,
        unavailable=unavailable,
        invalid_depot=invalid_depot,
    )
    session = SimpleNamespace(
        state=AuthState.ACTIVE,
        protocol=object(),
        authenticate=noop,
        welcome=ServerWelcome("controlled", "15.3", True, "simulated", 42, 0, 0, 64, 64),
    )
    counters = dict(launches=0, connections=0, cleanup=0)

    class Backend:
        def __init__(self, **kwargs):
            self.process = None
            self.session = None

        def preflight(self, p):
            pass

        def validate_launch(self, p):
            pass

        async def launch(self, p):
            self.process = SimpleNamespace(pid=123)
            counters["launches"] += 1

        async def cleanup(self, p):
            counters["cleanup"] += 1
            return dict(reaped=True, sockets_closed=True, cleanup_error=[], remaining_processes=[])

    async def connect(*args, **kwargs):
        counters["connections"] += 1
        session.observer = kwargs["frame_observer"]
        return session

    async def save(backend, p, name):
        path = p.directory / (name + ".sav")
        path.write_bytes(b"simulated vehicle save " + name.encode())
        return sha256(path)

    async def exchange(session, q, directory):
        if isinstance(q, proof.FreightRequest):
            vm.execute("bridge.Handle(" + q.to_bytes().decode() + ");")
            replies = vm.get_roottable()["replies"]
            table = replies[len(replies) - 1]
            d = {}
            for key in table.keys():
                k = str(key)
                v = table[k]
                if k in ("op", "request_id", "plan", "status"):
                    d[k] = str(v)
                elif k in ("road", "links"):
                    d[k] = [bool(v[i]) for i in range(len(v))]
                elif k in ("owners", "fronts", "costs"):
                    d[k] = [int(v[i]) for i in range(len(v))]
                elif k in ("stop", "truck", "depot", "eligible"):
                    d[k] = bool(v)
                else:
                    d[k] = int(v)
            value = proof.FreightReadback.parse_for(
                q, json.dumps(d, separators=(",", ":")).encode()
            )
        else:
            value = handle(vm, q)
            if corrupt_read and q.request_id == "read-purchase":
                value = value.model_copy(update={"capacity": 19})
        raw = value.to_bytes() if hasattr(value, "clock") else value.model_dump_json().encode()
        (directory / (q.request_id + "-request.json")).write_bytes(q.to_bytes())
        (directory / (q.request_id + "-response.json")).write_bytes(raw)
        session.observer("outbound", encode_gamescript(q.to_bytes()))
        session.observer("inbound", encode_admin_frame(SERVER_GAMESCRIPT, raw + b"\0"))
        return value

    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: pytest.fail("real process prohibited"))
    monkeypatch.setattr(proof, "VehicleBackend", Backend)
    monkeypatch.setattr(proof.VehicleSecureSession, "connect_secure", connect)
    monkeypatch.setattr(proof, "GameScriptTransport", lambda *a: SimpleNamespace(subscribe=noop))
    monkeypatch.setattr(proof, "wait_log", noop)
    monkeypatch.setattr(proof, "save", save)
    monkeypatch.setattr(proof, "exchange", exchange)
    monkeypatch.setattr(
        proof,
        "kernel_socket_rows",
        lambda: [dict(table="tcp", local_port=prepared.endpoints[1], state=10)],
    )
    monkeypatch.setattr(proof, "verify_cleanup_endpoints", lambda *a: {})
    result = asyncio.run(proof.run(prepared))
    return prepared, result, counters


def test_controlled_runner_complete_receipt_and_cleanup(tmp_path, monkeypatch):
    p, result, counters = controlled_run(tmp_path, monkeypatch)
    assert result["status"] == "NATIVE_STATE_VERIFIED" and result["mutation_requests"] == 3
    assert result["requests"] == 12
    assert counters == dict(launches=1, connections=1, cleanup=1)
    assert proof.verify_receipt(p.directory)["vehicle"] == 23
    with pytest.raises(ValueError, match="consumed"):
        proof.preflight(p)


@pytest.mark.parametrize(
    "kwargs,mutations",
    [
        ({"unavailable": True}, 0),
        ({"invalid_depot": True}, 0),
        ({"fail_order_test": True}, 1),
        ({"fail_order": True}, 2),
        ({"corrupt_read": True}, 1),
    ],
)
def test_runner_stops_on_admission_or_readback_failure(tmp_path, monkeypatch, kwargs, mutations):
    p, result, counters = controlled_run(tmp_path, monkeypatch, **kwargs)
    assert result["status"] == "FAILED" and result["mutation_requests"] == mutations
    assert not (p.directory / "receipt.json").exists()
    assert counters == dict(launches=1, connections=1, cleanup=1)
    assert json.loads((p.directory / "cleanup.json").read_text())["workspace_disposed"] is True


@pytest.mark.parametrize("defect", ["frame", "plan", "receipt", "save", "cleanup", "connections"])
def test_retained_receipt_corruption_fails_even_after_rehash(tmp_path, monkeypatch, defect):
    p, _, _ = controlled_run(tmp_path, monkeypatch)
    root = p.directory
    path = (
        root
        / {
            "frame": "frames.json",
            "plan": "plan.json",
            "receipt": "receipt.json",
            "save": "after.sav",
            "cleanup": "cleanup.json",
            "connections": "result.json",
        }[defect]
    )
    if defect == "save":
        path.write_bytes(b"altered save")
    else:
        d = json.loads(path.read_text())
        if defect == "frame":
            d.pop()
        elif defect == "plan":
            d["engine"] += 1
        elif defect == "receipt":
            d["vehicle"] += 1
        elif defect == "cleanup":
            d["sockets_closed"] = False
        else:
            d["connections"] = 2
        path.write_text(json.dumps(d))
    (root / "artifact-manifest.sha256").write_text(manifest(root))
    with pytest.raises(ValueError):
        proof.verify_receipt(root)


def test_package_identity_and_secure_action_allowlist():
    vm = SQVM()
    vm.execute(
        "class GSInfo {} function RegisterGS(v) { "
        'if(v.GetName()!="RoadFreightProof" || v.GetAPIVersion()!="15" || '
        'v.CreateInstance()!="RoadVehicleProof") throw "package"; }'
    )
    vm.execute((proof.PACKAGE / "info.nut").read_text())
    session = object.__new__(proof.VehicleSecureSession)
    session._state = AuthState.ACTIVE
    session.validate_outbound(encode_gamescript(request("purchase").to_bytes()))
    with pytest.raises(ValueError):
        session.validate_outbound(encode_gamescript(b'{"op":"sell"}'))
    with pytest.raises(ValueError):
        session.validate_outbound(
            encode_gamescript(
                proof.FreightRequest(
                    op="road",
                    request_id="bad",
                    plan=SEAL,
                    company=0,
                    start=1292,
                    end=1293,
                    max_cost=10000,
                ).to_bytes()
            )
        )
