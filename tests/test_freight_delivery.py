"""Controlled native-API simulation, never proof of actual freight delivery."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.simulation.openttd.freight_delivery import (
    DeliveryReadback,
    DeliveryRequest,
    admit,
    verify_delivery,
    verify_observation,
    verify_snapshot,
)
from app.simulation.openttd.proof import freight_delivery as proof
from tests.test_road_vehicle_lifecycle import vm_for

SEAL = "a" * 64


def delivery_vm(*, no_supply=False, no_payment=False, no_delivery=False, paused=False):
    vm = vm_for()
    vm.execute(f"""
        ::no_supply <- {str(no_supply).lower()};::no_payment <- {str(no_payment).lower()};
        ::no_delivery <- {str(no_delivery).lower()};::paused={str(paused).lower()};
        ::roads <- {{}};::roadbits <- {{}};
        ::stops <- {{}};::depots <- {{}};::actual <- 0;::dvid <- -1;
        ::ddorders <- [];::monitored <- false;
        ::GSDate <- class {{
            static function GetCurrentDate() {{return 700000+::ticks/74;}}
            static function GetYear(d) {{return 1950;}}static function GetMonth(d) {{return 1;}}
        }};
        ::GSIndustry <- class {{
            static CAS_ACCEPTED=1;
            static function IsValidIndustry(i) {{return i==7||i==8;}}
            static function GetIndustryID(t) {{return t==650?7:(t==1300?8:-1);}}
            static function GetLocation(i) {{return i==7?650:1300;}}
            static function GetIndustryType(i) {{return i==7?3:4;}}
            static function GetLastMonthProduction(i,c) {{return i==7&&c==3&&!::no_supply?100:0;}}
            static function IsCargoAccepted(i,c) {{return i==8&&c==3?1:0;}}
            static function GetCargoLastAcceptedDate(i,c) {{return (
                ::running&&::ticks>=25?GSDate.GetCurrentDate():-1);}}
        }};
        ::GSIndustryList_CargoProducing <- class {{i=0;constructor(c){{}}function Count(){{return (
                1);}}
            function Begin(){{i=0;
                return (
                7);}}function IsEnd(){{return i>0;}}function Next(){{i++;
                return 7;}}}};
        ::GSIndustryList_CargoAccepting <- class {{i=0;constructor(c){{}}function Count(){{return (
                1);}}
            function Begin(){{i=0;
                return (
                8);}}function IsEnd(){{return i>0;}}function Next(){{i++;
                return 8;}}}};
        ::GSCompany = class {{static COMPANY_INVALID=-1;static CURRENT_QUARTER=0;
            static function ResolveCompanyID(c){{return c==0?0:-1;}}
            static function GetBankBalance(c){{return ::funds;}}
            static function GetQuarterlyCargoDelivered(c,q){{return (
                ::running&&::ticks>=25&&!::no_delivery?20:0);}}
            static function GetQuarterlyIncome(c,q){{return (
                ::running&&::ticks>=25&&!::no_payment?500:0);}}
        }};
        ::GSTile = class {{static TRANSPORT_ROAD=0;
            static TRANSPORT_RAIL=1;
            static TRANSPORT_WATER=2;
            static TRANSPORT_AIR=3;
            static function IsBuildable(t){{return (
                !(t in ::roads)&&!(t in ::stops)&&!(t in ::depots)&&t!=650&&t!=1300);}}
            static function GetOwner(t){{return t in ::roads||t in ::stops||t in ::depots?0:-1;}}
            static function GetSlope(t){{return 0;}}static function GetMinHeight(t){{return 1;}}
            static function IsWaterTile(t){{return (
                false);}}static function IsCoastTile(t){{return false;}}
            static function HasTreeOnTile(t){{return (
                false);}}static function IsFarmTile(t){{return false;}}
            static function IsRockTile(t){{return (
                false);}}static function IsRoughTile(t){{return false;}}
            static function HasTransportType(t,k){{return t in ::roads;}}
            static function GetCargoProduction(t,c,w,h,r){{return 1;}}
            static function GetCargoAcceptance(t,c,w,h,r){{return 8;}}
        }};
        ::GSRoad = class {{static ROADTYPE_ROAD=0;static ROADVEHTYPE_TRUCK=1;
            static function SetCurrentRoadType(t){{}}static function GetCurrentRoadType(){{return (
                0);}}
            static function IsRoadTypeAvailable(t){{return true;}}
            static function CanRunOnRoad(e,t){{return true;}}
            static function GetRoadVehicleTypeForCargo(c){{return 1;}}
            static function IsRoadTile(t){{return t in ::roads;}}
            static function IsRoadStationTile(t){{return t in ::stops;}}
            static function IsDriveThroughRoadStationTile(t){{return false;}}
            static function GetRoadStationFrontTile(t){{return ::stops[t];}}
            static function IsRoadDepotTile(t){{return t in ::depots;}}
            static function GetRoadDepotFrontTile(t){{return ::depots[t];}}
            static function HasBit(t,f){{
                if(t in ::stops)return ::stops[t]==f;
                if(t in ::depots)return ::depots[t]==f;
                return t in ::roadbits&&(f-t) in ::roadbits[t];}}
            static function AreRoadTilesConnected(a,b){{return HasBit(a,b)&&HasBit(b,a);}}
            static function BuildRoad(a,b){{::cost=100;if(::account in ::tests)return true;
                ::funds-=100;::actual++;::roads[a]<-true;::roads[b]<-true;
                foreach(t in [a,b]){{if(!(t in ::roadbits))::roadbits[t]<-{{}};
                    ::roadbits[t][t==a?b-a:a-b]<-true;}}return true;}}
            static function BuildRoadFull(a,b){{::cost=100;if(::account in ::tests)return true;
                ::funds-=100;::actual++;local step=a/64==b/64?(b>a?1:-1):(b>a?64:-64);
                for(local t=a;;t+=step){{::roads[t]<-true;
                    if(!(t in ::roadbits))::roadbits[t]<-{{}};
                    ::roadbits[t][step]<-true;::roadbits[t][-step]<-true;if(t==b)break;}}
                return true;}}
            static function BuildRoadStation(t,f,k,s){{::cost=100;
                if(::account in ::tests)return (
                true);
                ::funds-=100;::actual++;::stops[t]<-f;return true;}}
            static function BuildRoadDepot(t,f){{::cost=100;if(::account in ::tests)return true;
                ::funds-=100;::actual++;::depots[t]<-f;return true;}}
        }};
        ::GSStation = class {{static STATION_TRUCK_STOP=2;
            static STATION_BUS_STOP=4;
            static STATION_NEW=-1;
            static function GetCoverageRadius(k){{return 3;}}
            static function GetStationID(t){{return t in ::stops?(t==::bridge.choice.a[4]?1:2):-1;}}
            static function GetCargoWaiting(s,c){{return ::running?30:0;}}
        }};
        ::GSVehicleList = class {{function Count(){{return ::dvid>=0?1:0;}}}};
        ::GSVehicle = class {{static VT_ROAD=1;
            static VS_RUNNING=0;
            static VS_IN_DEPOT=2;
            static VS_AT_STATION=3;
            static function IsValidVehicle(v){{return v==23&&::dvid==23;}}
            static function IsPrimaryVehicle(v){{return IsValidVehicle(v);}}
            static function GetOwner(v){{return 0;}}static function GetEngineType(v){{return 42;}}
            static function GetCapacity(v,c){{return 20;}}
            static function GetLocation(v){{return (
                !::running?::bridge.choice.a[8]:
                (::ticks<20?::bridge.choice.a[4] : ::bridge.choice.a[6]));}}
            static function GetState(v){{return ::running?3:2;}}
            static function GetCurrentSpeed(v){{return 0;}}
            static function IsInDepot(v){{return !::running;}}
            static function GetCargoLoad(v,c){{return ::running&&::ticks>=5&&::ticks<25?20:0;}}
            static function GetProfitThisYear(v){{return (
                ::running&&::ticks>=25&&!::no_payment?480:0);}}
            static function BuildVehicle(d,e){{::cost=5000;if(::account in ::tests)return 0;
                ::funds-=5000;::actual++;::dvid=23;return 23;}}
            static function StartStopVehicle(v){{::cost=0;if(::account in ::tests)return true;
                ::actual++;::running=true;return true;}}
        }};
        ::GSOrder = class {{static OF_FULL_LOAD=64;static OF_NO_LOAD=128;
            static function GetOrderCount(v){{return ::ddorders.len();}}
            static function GetOrderDestination(v,i){{return ::ddorders[i][0];}}
            static function GetOrderFlags(v,i){{return ::ddorders[i][1];}}
            static function IsGotoStationOrder(v,i){{return i<::ddorders.len();}}
            static function AppendOrder(v,t,f){{::cost=0;if(::account in ::tests)return true;
                ::actual++;::ddorders.append([t,f]);return true;}}
        }};
        ::GSCargoMonitor <- class {{
            static function GetIndustryPickupAmount(company,cargo,industry,keep){{
                if(company!=0||cargo!=3||industry!=7)throw "bad pickup monitor";
                return keep?0:(::no_delivery?0:20);}}
            static function GetIndustryDeliveryAmount(company,cargo,industry,keep){{
                if(company!=0||cargo!=3||industry!=8)throw "bad delivery monitor";
                return keep?0:(::no_delivery?0:20);}}
        }};
    """)
    vm.execute((proof.PACKAGE / "main.nut").read_text().replace('require("vehicle.nut");', ""))
    vm.execute("::bridge=FreightDeliveryProof();")
    return vm


def call(vm, op, id, arg=0, plan=SEAL):
    q = DeliveryRequest(op=op, request_id=id, arg=arg, plan=plan)
    vm.execute("bridge.Handle(" + q.to_bytes().decode() + ");")
    replies = vm.get_roottable()["replies"]
    r = replies[len(replies) - 1]
    data = {}
    for key in r.keys():
        k = str(key)
        v = r[k]
        data[k] = (
            str(v)
            if k in ("op", "request_id", "plan", "status")
            else [int(v[i]) for i in range(len(v))]
            if k in ("a", "f", "s")
            else int(v)
        )
    return DeliveryReadback.parse_for(q, json.dumps(data, separators=(",", ":")).encode())


def complete(vm):
    inspect = call(vm, "inspect", "inspect-1")
    plan = admit(inspect, SEAL, "b" * 64, "c" * 64)
    baseline = None
    records = []
    for i in range(10):
        built = call(vm, "build", f"build-{i}", i, plan.digest)
        assert built.status == "BUILT"
        read = call(vm, "read", f"read-{i}", i, plan.digest)
        verify_snapshot(plan, read)
        if i == 8:
            baseline = read
    for i in range(4):
        r = call(vm, "observe", f"observe-{i}", i, plan.digest)
        verify_observation(plan, r, i)
        records.append(r)
    final = call(vm, "finish", "finish-1", 0, plan.digest)
    return plan, baseline, records, final


def test_actual_bridge_loading_arrival_final_delivery_and_payment():
    vm = delivery_vm()
    plan, baseline, records, final = complete(vm)
    receipt = verify_delivery(plan, baseline, records, final)
    assert receipt["loaded"] == receipt["delivered"] == receipt["pickup_monitor"] == 20
    assert receipt["payment_income"] == 500 and receipt["vehicle_profit_delta"] == 480
    assert int(vm.get_roottable()["actual"]) == 10
    assert records[1].s[8] == plan.a[4] and records[2].s[8] == plan.a[6]


@pytest.mark.parametrize("kwargs", [{"no_supply": True}, {"paused": True}])
def test_native_admission_failure_never_constructs(kwargs):
    vm = delivery_vm(**kwargs)
    r = call(vm, "inspect", "inspect-1")
    with pytest.raises(ValueError):
        admit(r, SEAL, "b" * 64, "c" * 64)
    assert int(vm.get_roottable()["actual"]) == 0


@pytest.mark.parametrize(
    "index,value", [(24, 0), (25, 0), (18, 0), (19, 0), (20, 0), (11, 20), (5, 1), (29, 0)]
)
def test_monitor_payment_unload_and_readback_mismatches_cannot_prove_delivery(index, value):
    plan, baseline, records, final = complete(delivery_vm())
    values = list(final.s)
    values[index] = value
    with pytest.raises(ValueError):
        verify_delivery(plan, baseline, records, final.model_copy(update={"s": tuple(values)}))


def test_no_payment_exhaustion_is_inconclusive():
    vm = delivery_vm(no_payment=True)
    with pytest.raises(ValueError, match="inconclusive"):
        complete(vm)
    assert int(vm.get_roottable()["ticks"]) <= 2068


def test_packets_and_duplicate_keys_are_bounded():
    vm = delivery_vm()
    r = call(vm, "inspect", "inspect-1")
    raw = r.model_dump_json().encode()
    assert len(raw) <= 512
    q = DeliveryRequest(op="inspect", request_id="inspect-1", plan=SEAL)
    with pytest.raises(ValueError, match="duplicate"):
        DeliveryReadback.parse_for(q, raw[:-1] + b',"arg":0}')
    with pytest.raises(ValueError, match="512"):
        DeliveryReadback.parse_for(q, b" " * 513)


def test_deadline_sends_once_without_retry(tmp_path):
    async def receive():
        await asyncio.Event().wait()

    sent = []

    async def send(raw):
        sent.append(raw)

    async def run():
        async with asyncio.timeout(0.01):
            await proof.exchange(
                SimpleNamespace(send=send, receive=receive),
                DeliveryRequest(op="observe", request_id="deadline", plan=SEAL),
                tmp_path,
            )

    with pytest.raises(TimeoutError):
        asyncio.run(run())
    assert len(sent) == 1


@pytest.mark.parametrize("failure", [None, "supply", "purchase", "order", "payment"])
def test_controlled_one_shot_runner_receipt_and_failure_cleanup(tmp_path, monkeypatch, failure):
    """Simulated process/secure peer only; this is never native proof evidence."""
    import shutil
    from dataclasses import dataclass

    from app.simulation.openttd.gamescript_transport import ADMIN_GAMESCRIPT, encode_gamescript

    vm = delivery_vm(no_supply=failure == "supply", no_payment=failure == "payment")
    if failure in ("purchase", "order"):
        api, method = (
            ("GSVehicle", "BuildVehicle") if failure == "purchase" else ("GSOrder", "AppendOrder")
        )
        if failure == "purchase":
            vm.execute(
                "GSVehicle.BuildVehicle <- function(a,b) {::cost=5000;"
                "return ::account in ::tests ? 0 : -1;};"
            )
        else:
            vm.execute(
                f"{api}.{method} <- function(a,b,c=null) {{::cost=0;"
                "return ::account in ::tests ? true : false;};"
            )
    root = tmp_path / "isolated/world"
    logs = root / "logs"
    logs.mkdir(parents=True)
    key = root / ".admin-secret"
    key.write_bytes(proof.AuthorizedKey.generate()._secret)
    workspace = SimpleNamespace(root=root, logs=logs, close=lambda: shutil.rmtree(root))
    p = SimpleNamespace(
        directory=tmp_path,
        key_path=key,
        endpoints=(1, 2),
        spec=SimpleNamespace(workspace=workspace),
    )
    metadata = dict(
        schema="first-freight-delivery-prelaunch-v1",
        budgets=proof.BUDGETS,
        source=dict(
            save_sha256=proof.sha256(proof.SOURCE / "before.sav"),
            receipt_sha256=proof.sha256(proof.SOURCE / "receipt.json"),
        ),
        predecessor=dict(receipt_sha256=proof.sha256(proof.PREVIOUS / "receipt.json")),
    )
    proof.write_json(tmp_path / "PRELAUNCH.json", metadata)
    (tmp_path / "PRELAUNCH.sha256").write_text(proof.sha256(tmp_path / "PRELAUNCH.json"))

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
        async def connect_secure(cls, *args, frame_observer, **kwargs):
            session = cls(frame_observer)
            return session

        def __init__(self, observer):
            self.observer = observer

        async def authenticate(self, *args, **kwargs):
            pass

        async def send(self, raw):
            self.observer("outbound", raw)
            if raw[2] == ADMIN_GAMESCRIPT:
                q = DeliveryRequest.model_validate_json(proof.decode_gamescript(raw[3:]))
                r = call(vm, q.op, q.request_id, q.arg, q.plan)
                data = encode_gamescript(r.model_dump_json().encode())
                self.reply = data[:2] + bytes([proof.SERVER_GAMESCRIPT]) + data[3:]

        async def receive(self):
            self.observer("inbound", self.reply)
            return self.reply

    class Backend:
        def __init__(self, **kwargs):
            self.process = None

        async def launch(self, prepared):
            self.process = SimpleNamespace()

        async def cleanup(self, prepared):
            key.unlink()
            return dict(reaped=True, sockets_closed=True, remaining_processes=[], cleanup_error=[])

    class Transport:
        def __init__(self, *args):
            pass

        async def subscribe(self):
            pass

    async def save(*args):
        path = tmp_path / (args[2] + ".sav")
        path.write_bytes(b"controlled save fixture")
        return proof.sha256(path)

    async def wait(*args):
        pass

    monkeypatch.setattr(proof, "preflight", lambda p: None)
    monkeypatch.setattr(proof.vehicle, "VehicleBackend", Backend)
    monkeypatch.setattr(proof, "DeliverySession", Session)
    monkeypatch.setattr(proof, "GameScriptTransport", Transport)
    monkeypatch.setattr(proof, "wait_log", wait)
    monkeypatch.setattr(proof, "save", save)
    monkeypatch.setattr(proof, "verify_cleanup_endpoints", lambda *args: {})
    result = asyncio.run(proof.run(p))
    assert result["launches"] == result["connections"] == 1  # simulated, never native
    assert not root.exists() and not key.exists()
    if failure is None:
        assert result["status"] == "NATIVE_DELIVERY_VERIFIED", result
        receipt = proof.verify_receipt(tmp_path)
        assert receipt["delivered"] == 20 and result["requests"] == 26
        frames = json.loads((tmp_path / "frames.json").read_text())
        frames[0], frames[2] = frames[2], frames[0]
        (tmp_path / "frames.json").write_text(json.dumps(frames))
        (tmp_path / "artifact-manifest.sha256").write_text(proof.manifest(tmp_path))
        with pytest.raises(ValueError, match="ordered"):
            proof.verify_receipt(tmp_path)
    else:
        assert result["status"] == "FAILED" and result["requests"] <= 25
        assert not (tmp_path / "receipt.json").exists()
        assert (tmp_path / "failure.sav").is_file()


def test_stale_sealed_source_rejected_before_backend(tmp_path, monkeypatch):
    tmp_path = tmp_path / "openttd-15.3-first-freight-delivery-attempt1"
    tmp_path.mkdir()
    source = tmp_path / "source.nut"
    source.write_text("old frozen source")
    m = dict(
        schema="first-freight-delivery-prelaunch-v1",
        attempt=1,
        budgets=proof.BUDGETS,
        frozen={str(source): proof.sha256(source)},
    )
    proof.write_json(tmp_path / "PRELAUNCH.json", m)
    (tmp_path / "PRELAUNCH.sha256").write_text(proof.sha256(tmp_path / "PRELAUNCH.json"))
    source.write_text("stale package")

    def prohibited(*args, **kwargs):
        pytest.fail("backend reached after failing preflight")

    monkeypatch.setattr(proof.vehicle, "VehicleBackend", prohibited)
    with pytest.raises(ValueError, match="Frozen source/input changed"):
        proof.preflight(SimpleNamespace(directory=tmp_path))


@pytest.mark.parametrize(
    "change",
    [
        "::funds=1;",
        "GSEngine.IsBuildable <- function(e) {return false;};",
        "GSTile.GetCargoAcceptance <- function(t,c,w,h,r) {return 0;};",
    ],
)
def test_insufficient_funds_unavailable_engine_and_no_acceptance_stop_before_mutation(change):
    vm = delivery_vm()
    vm.execute(change)
    with pytest.raises(ValueError):
        admit(call(vm, "inspect", "inspect-1"), SEAL, "b" * 64, "c" * 64)
    assert int(vm.get_roottable()["actual"]) == 0


def test_missing_loading_arrival_or_wrong_vehicle_cannot_verify():
    plan, baseline, records, final = complete(delivery_vm())
    with pytest.raises(ValueError, match="four ordered"):
        verify_delivery(plan, baseline, records[:3], final)
    values = list(records[2].s)
    values[8] = plan.a[4]
    bad = records[:2] + [records[2].model_copy(update={"s": tuple(values)})] + records[3:]
    with pytest.raises(ValueError, match="destination arrival"):
        verify_delivery(plan, baseline, bad, final)


def test_mutation_request_requires_active_encryption_and_valid_frame():
    session = object.__new__(proof.DeliverySession)
    session._state = proof.AuthState.ACTIVE
    q = DeliveryRequest(op="build", request_id="build-0", plan=SEAL)
    frame = proof.encode_gamescript(q.to_bytes())
    session.validate_outbound(frame)
    with pytest.raises(ValueError, match="framed"):
        session.validate_outbound(frame[:-1])
    session._state = proof.AuthState.DISCONNECTED
    with pytest.raises(ValueError, match="ACTIVE"):
        session.validate_outbound(frame)


def test_depot_spur_requires_actual_front_road_bit():
    vm = delivery_vm()
    vm.execute(
        "GSRoad.BuildRoad <- function(a,b) {::cost=100;"
        "if(::account in ::tests)return true;::funds-=100;::actual++;return true;};"
    )
    inspect = call(vm, "inspect", "inspect-1")
    plan = admit(inspect, SEAL, "b" * 64, "c" * 64)
    for i in range(6):
        assert call(vm, "build", f"build-{i}", i, plan.digest).status == "BUILT"
    read = call(vm, "read", "read-5", 5, plan.digest)
    with pytest.raises(ValueError, match="connected owned route"):
        verify_snapshot(plan, read)
    rejected = call(vm, "build", "build-6", 6, plan.digest)
    assert rejected.status == "INVALID_ROUTE" and rejected.s[4] == -1


@pytest.mark.parametrize(
    "change,status",
    [
        ("::paused=true;", "PAUSED"),
        (
            "GSStation.GetCargoWaiting <- function(s,c) {return 0;};::frozen_clock=true;",
            "CLOCK_STALLED",
        ),
        ("::ticks=74;GSDate.GetMonth <- function(d) {return d>700000?4:1;};", "WINDOW_EXHAUSTED"),
        (
            "::dates <- 700000;GSDate.GetCurrentDate <- function() {::dates+=31;return ::dates;};",
            "WINDOW_EXHAUSTED",
        ),
    ],
)
def test_observation_pause_clock_and_economy_window_fail_closed(change, status):
    vm = delivery_vm()
    admission = call(vm, "inspect", "inspect-1")
    plan = admit(admission, SEAL, "b" * 64, "c" * 64)
    for i in range(10):
        assert call(vm, "build", f"build-{i}", i, plan.digest).status == "BUILT"
    vm.execute(change)
    r = call(vm, "observe", "observe-0", 0, plan.digest)
    assert r.status == status
    with pytest.raises(ValueError):
        verify_observation(plan, r, 0)
    assert int(vm.get_roottable()["actual"]) == 10


@pytest.mark.parametrize(
    "override,reason,count",
    [
        ("", "no_supply", 0),
        (
            "::no_supply=false;"
            "::GSTile=class extends GSTile {static function "
            "GetCargoProduction(t,c,w,h,r){return 2;}};",
            "production_count",
            18,
        ),
        (
            "::no_supply=false;"
            "::GSTile=class extends GSTile {static function "
            "GetCargoAcceptance(t,c,w,h,r){return 7;}};",
            "acceptance",
            18,
        ),
        (
            "::no_supply=false;"
            "::GSTile=class extends GSTile {static function IsBuildable(t){return false;}};",
            "footprint",
            18,
        ),
    ],
)
def test_admission_rejection_counters(override, reason, count):
    from app.simulation.openttd.freight_delivery import admission_diagnostics

    vm = delivery_vm(no_supply=True)
    if override:
        vm.execute(override)
    r = call(vm, "inspect", "inspect-1")
    diagnostic = admission_diagnostics(r)
    assert diagnostic["classification"] == "CANDIDATES_REJECTED"
    assert diagnostic["first_rejection"] == reason
    assert diagnostic["counters"]["pairs"] == 2
    assert diagnostic["counters"]["layouts"] == count
    assert diagnostic["counters"][reason] == (count or 2)
    assert int(vm.get_roottable()["actual"]) == 0
    assert len(r.model_dump_json().encode()) <= 512
    bad = list(r.a)
    bad[6] += 1
    with pytest.raises(ValueError, match="diagnostics"):
        admission_diagnostics(r.model_copy(update={"a": tuple(bad)}))


def test_no_compatible_engines_is_no_candidates():
    from app.simulation.openttd.freight_delivery import admission_diagnostics

    vm = delivery_vm()
    vm.execute("::available=false;")
    r = call(vm, "inspect", "inspect-1")
    d = admission_diagnostics(r)
    assert d["classification"] == "NO_CANDIDATES_GENERATED"
    assert d["first_rejection"] is None
    assert d["counters"]["engines_seen"] == 2
    assert d["counters"]["engines_compatible"] == 0


def test_retained_attempt_has_no_gate_diagnostics():
    from app.simulation.openttd.freight_delivery import admission_diagnostics

    directory = proof.PROJECT / "artifacts/runtime/openttd-15.3-first-freight-delivery-attempt1"
    q = DeliveryRequest.model_validate_json((directory / "inspect-1-request.json").read_bytes())
    r = DeliveryReadback.parse_for(q, (directory / "inspect-1-response.json").read_bytes())
    assert r.status == "NO_NATIVE_FEASIBLE_OD"
    assert admission_diagnostics(r) is None
    with pytest.raises(ValueError, match="admission required"):
        admit(r, q.plan, "b" * 64, "c" * 64)


def test_diagnostic_maximum_counters_fit_response_limit():
    from app.simulation.openttd.freight_delivery import admission_diagnostics

    r = call(delivery_vm(no_supply=True), "inspect", "x" * 32)
    a = (33, 32, 32768, 0, 32704, 0, 64, 0, 64, 0)
    s = list(r.s)
    for index in (0, 1, 3, 26):
        s[index] = 2147483647
    s[28] = 5
    r = r.model_copy(update={"a": a, "f": (0,) * 8, "s": tuple(s)})
    raw = r.model_dump_json().encode()
    assert len(raw) <= 512
    q = DeliveryRequest(op="inspect", request_id="x" * 32, plan=SEAL)
    assert (
        admission_diagnostics(DeliveryReadback.parse_for(q, raw))["first_rejection"] == "no_supply"
    )
    bad = r.model_copy(update={"f": (65,) + (0,) * 7})
    with pytest.raises(ValueError, match="diagnostics"):
        DeliveryReadback.parse_for(q, bad.model_dump_json().encode())


@pytest.mark.parametrize(
    "override,status,classification",
    [
        ("::paused=true;", "INVALID_WORLD", "PRECONDITION_REJECTED"),
        (
            "::GSEngineList=class {i=0;constructor(k){}function Begin(){return 42;}"
            "function Next(){i++;return 42;}function IsEnd(){return i>=33;}};",
            "ENGINE_LIMIT",
            "SEARCH_LIMIT_REACHED",
        ),
    ],
)
def test_diagnostics_do_not_call_preconditions_or_limits_candidate_exhaustion(
    override, status, classification
):
    from app.simulation.openttd.freight_delivery import admission_diagnostics

    vm = delivery_vm()
    vm.execute(override)
    r = call(vm, "inspect", "inspect-1")
    assert r.status == status
    assert admission_diagnostics(r)["classification"] == classification
    assert int(vm.get_roottable()["actual"]) == 0


def test_vehicle_quote_waits_for_real_depot_and_still_checks_native_price():
    vm = delivery_vm()
    vm.execute("""
        GSVehicle.BuildVehicle <- function(d,e) {
            if(!(d in ::depots)){::cost=0;return -1;}
            ::cost=5000;if(::account in ::tests)return 0;
            ::funds-=5000;::actual++;::dvid=23;return 23;
        };
    """)
    plan, baseline, records, final = complete(vm)
    assert verify_delivery(plan, baseline, records, final)["delivered"] == 20


def test_native_demo_preparation_uses_real_commands_and_bounded_vacancy_readbacks():
    vm = delivery_vm()
    vm.execute("""
        ::industry_builds <- 0;
        ::GSMap=class extends GSMap {
            static function GetMapSizeX(){return 64;}
            static function GetMapSizeY(){return 64;}
        };
        ::GSIndustry=class extends GSIndustry {
            static function GetIndustryCount(){return ::industry_builds;}
            static function GetIndustryType(i){return i==7?0:1;}
            static function GetLocation(i){return i==7?1300:1828;}
        };
        ::DemoCargoList <- class {
            function Count(){return 1;} function Begin(){return 3;}
            function HasItem(c){return c==3;}
        };
        ::GSIndustryType <- class {
            static function GetProducedCargo(t){return DemoCargoList();}
            static function GetAcceptedCargo(t){return DemoCargoList();}
            static function IsRawIndustry(t){return t==0;}
            static function BuildIndustry(t,tile){
                if(tile!=(t==0?1300:1828))throw "wrong native industry tile";
                ::industry_builds++;return true;
            }
        };
        ::GSIndustryList <- class {
            i=0;function Count(){return 2;}function Begin(){return 7;}
            function Next(){i++;return 8;}function IsEnd(){return i>=2;}
        };
    """)
    vm.execute((proof.PACKAGE / "demo.nut").read_text().replace('require("delivery.nut");', ""))
    vm.execute("::demo<-FreightDemoProof();demo.PrepareDemo();")
    assert int(vm.get_roottable()["industry_builds"]) == 2
    assert (
        int(vm.get_roottable()["actual"]) == 0
    )  # No service construction during world preparation.


def test_demo_heightmap_and_staged_package_are_deterministic():
    import struct
    import zlib

    png = proof.flat_heightmap()
    assert png == proof.flat_heightmap()
    assert struct.unpack(">II", png[16:24]) == (64, 64)
    offset = png.index(b"IDAT")
    size = struct.unpack(">I", png[offset - 4 : offset])[0]
    assert zlib.decompress(png[offset + 4 : offset + 4 + size]) == (b"\0" + b"\1" * 64) * 64
    staged = proof.staged_package(True)
    assert staged["delivery.nut"] == (proof.PACKAGE / "main.nut").read_bytes()
    assert staged["main.nut"] == (proof.PACKAGE / "demo.nut").read_bytes()
    assert b'"FreightDemoProof"' in staged["info.nut"]


def test_demo_prepares_without_historical_saves_and_never_launches(tmp_path, monkeypatch):
    monkeypatch.setattr(proof, "SOURCE", tmp_path / "absent-source")
    monkeypatch.setattr(proof, "PREVIOUS", tmp_path / "absent-receipt")

    def forbidden(*args, **kwargs):
        pytest.fail("preparation created a process or Admin connection")

    monkeypatch.setattr(proof.DemoBackend, "launch", forbidden)
    monkeypatch.setattr(proof.DeliverySession, "connect_secure", forbidden)
    p = proof.prepare(tmp_path / "openttd-15.3-first-freight-delivery-attempt1", demo=True)
    try:
        proof.preflight(p)
        m = json.loads((p.directory / "PRELAUNCH.json").read_text())
        assert m["demo"] is True and m["source"]["kind"] == "NATIVE_FLAT_HEIGHTMAP"
        assert m["delivery_predecessor"] is None
        assert (p.spec.workspace.root / "heightmap.png").read_bytes() == proof.flat_heightmap()
        assert m["execution_command"][-1] == "--authorize-one-launch"
        assert not (p.directory / "CLAIM.json").exists()
    finally:
        p.spec.workspace.close()


def test_cli_requires_explicit_launch_authorization(tmp_path, monkeypatch, capsys):
    import sys

    monkeypatch.setattr(sys, "argv", ["freight", "run", str(tmp_path)])
    with pytest.raises(SystemExit) as error:
        proof.main()
    assert error.value.code == 2
    assert "--authorize-one-launch" in capsys.readouterr().err
    assert not (tmp_path / "CLAIM.json").exists()
