"""Controlled wire collection only; never starts a native runtime."""

import asyncio
import copy
import json

import pytest

from app.simulation.openttd.freight_canonical_runtime import (
    CanonicalPage,
    CanonicalRequest,
    collect_canonical,
)
from tests.test_freight_canonical import observation


def payload(request, **updates):
    row = dict(
        protocol=1,
        type="canonical-page-result",
        request_id=request.request_id,
        section=request.section,
        offset=request.offset,
        status="ok",
        total=1,
        records=[{}],
        tick=1,
        economy_date=700000,
        paused=True,
        restored=True,
    )
    row.update(updates)
    return json.dumps(row).encode()


@pytest.mark.parametrize(
    "changes",
    [
        dict(request_id="other"),
        dict(offset=1),
        dict(paused=False),
        dict(total=4097),
        dict(records=[]),
        dict(records=[{}] * 9),
    ],
)
def test_page_rejects_uncorrelated_or_incomplete(changes):
    q = CanonicalRequest("read-1", "header")
    with pytest.raises(ValueError):
        CanonicalPage.parse_for(q, payload(q, **changes))


def test_duplicate_keys_rejected():
    q = CanonicalRequest("read-1", "header")
    with pytest.raises(ValueError, match="duplicate"):
        CanonicalPage.parse_for(
            q, payload(q).replace(b'"protocol": 1', b'"protocol": 1,"protocol":1')
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "none",
        "missing-map",
        "duplicate-vehicle",
        "not-restored",
        "clock-drift",
        "cash-drift",
        "missing-station",
        "wrong-station-owner",
    ],
)
def test_bounded_native_collector(tmp_path, monkeypatch, mutation):
    from app.simulation.openttd import freight_canonical_save

    state = copy.deepcopy(observation()["state"])
    header = {
        k: v
        for k, v in state.items()
        if k not in ("map", "vehicles", "industries_production", "stations_cargo", "infrastructure")
    }
    header.update(
        width=10,
        height=1,
        vehicle_count=3,
        service_plans=["a" * 64, "b" * 64, "c" * 64],
        calendar_date=None,
        calendar_date_fraction=None,
        economy_date_fraction=None,
    )
    sections = dict(
        header=[header],
        vehicles=[copy.deepcopy(v) for v in state["vehicles"]],
        map=[
            dict(
                tile=i,
                owner=0,
                depot=i < 3,
                station=i if i >= 3 else 65535,
                edges=([i - 1] if i else []) + ([i + 1] if i < 9 else []),
            )
            for i in range(10)
        ],
        industries=state["industries_production"],
        stations=[dict(station=i, tile=i, owner=0, cargo=[[2, 0]]) for i in range(3, 9)],
    )
    for i, vehicle in enumerate(sections["vehicles"]):
        vehicle["tile"] = i
        vehicle["orders"][0]["destination"] = 3 + i * 2
        vehicle["orders"][1]["destination"] = 4 + i * 2
    if mutation == "missing-station":
        sections["stations"].pop()
    if mutation == "wrong-station-owner":
        sections["stations"][0]["owner"] = 1
    if mutation == "missing-map":
        sections["map"] = []
    if mutation == "duplicate-vehicle":
        sections["vehicles"][1]["vehicle"] = 1
    monkeypatch.setattr(
        freight_canonical_save,
        "read_save_clock",
        lambda path: dict(
            date=700000,
            date_fract=3,
            economy_date=700001 if mutation == "clock-drift" else 700000,
            economy_date_fract=3,
            tick_counter=100,
            calendar_sub_date_fract=4,
            pause_mode=1,
        ),
    )

    async def exchange(session, q, directory, *, response_type):
        rows = copy.deepcopy(sections[q.section][q.offset : q.offset + 1])
        if q.request_id.endswith("-header-final") and mutation == "cash-drift":
            rows[0]["cash"] -= 1
        raw = payload(
            q, total=len(sections[q.section]), records=rows, restored=mutation != "not-restored"
        )
        (directory / (q.request_id + "-response.json")).write_bytes(raw)
        return response_type.parse_for(q, raw)

    call = collect_canonical(
        None,
        tmp_path,
        identity="reload",
        runtime_sha256="a" * 64,
        bridge_sha256="b" * 64,
        configuration_sha256="c" * 64,
        source_save_sha256="d" * 64,
        snapshot_path=tmp_path / "snapshot.sav",
        require_restored=True,
        exchange_fn=exchange,
    )
    if mutation != "none":
        with pytest.raises(ValueError):
            asyncio.run(call)
    else:
        result = asyncio.run(call)
        assert result.state.map["service_plans"] == ["a" * 64, "b" * 64, "c" * 64]
        assert result.state.economy_date_fraction == 3
        assert result.state.map["saved_clock"]["tick_counter"] == 100
        assert (tmp_path / "canonical-readback.jsonl").exists()


@pytest.mark.parametrize("started", [False, True])
@pytest.mark.parametrize("arm", ["A", "B"])
def test_intervention_snapshot_allows_only_purchase_and_start(tmp_path, monkeypatch, started, arm):
    from app.simulation.openttd import freight_canonical_runtime as runtime
    from tests.test_freight_canonical import parse

    canonical = parse(observation()).state
    state = canonical.model_dump(mode="json")
    capex = 100 if arm == "B" else 0
    state["cash"] -= capex
    for vehicle in state["vehicles"]:
        vehicle["stopped"] = not started
    binding = dict(service=1, vehicle=99, purchase_capex=capex) if arm == "B" else None

    async def collect(*args, **kwargs):
        assert kwargs["expected_vehicle_count"] == (4 if arm == "B" else 3)
        return dict(state=copy.deepcopy(state))

    monkeypatch.setattr(runtime, "collect_raw_canonical", collect)
    assert asyncio.run(
        runtime.verify_intervention_snapshot(
            None, tmp_path, canonical=canonical, binding=binding, capex=capex, started=started
        )
    )
    state["loan"] += 1
    with pytest.raises(ValueError, match="semantic drift"):
        asyncio.run(
            runtime.verify_intervention_snapshot(
                None, tmp_path, canonical=canonical, binding=binding, capex=capex, started=started
            )
        )


def packaged_collector_vm():
    from pathlib import Path

    from test_freight_canonical_dispatch import canonical_vm

    vm = canonical_vm()
    vm.execute(
        Path("app/simulation/openttd/freight_delivery_package/canonical-collector.nut").read_text()
    )
    vm.execute("""
        ::GSCompany=class extends GSCompany {
            static function GetQuarterlyCargoDelivered(c,q){return 0;}
        };
        ::GSMap <- class {
            static function GetMapSizeX(){return 64;}
            static function GetMapSizeY(){return 64;}
            static function GetMapSize(){return 4096;}
            static function DistanceManhattan(a,b){return abs(a%64-b%64)+abs(a/64-b/64);}
        };
        ::GSTile=class extends GSTile {
            static function GetOwner(t){return 0;}
            static function GetSlope(t){return 0;}
            static function GetMinHeight(t){return 1;}
        };
        ::GSRoad=class extends GSRoad {
            static function IsRoadTile(t){return true;}
            static function IsRoadDepotTile(t){return t>=50&&t<=52;}
            static function AreRoadTilesConnected(a,b){return GSMap.DistanceManhattan(a,b)==1;}
        };
        ::GSStation=class extends GSStation {
            static STATION_ANY=31;
            static function GetStationID(t){return t;}
            static function GetLocation(s){return s;}
            static function GetCargoWaiting(s,c){return s+c;}
        };
        ::GSIndustry=class extends GSIndustry {
            static function GetIndustryID(t){return 65535;}
            static function GetIndustryType(i){return 0;}
            static function GetLocation(i){return 100+i;}
            static function IsCargoAccepted(i,c){return 1;}
            static function GetLastMonthProduction(i,c){return 25;}
        };
        function NativeList(ids){local t={};foreach(id in ids)t[id]<-0;
            t.setdelegate({Count=function(){return this.len();}});return t;}
        ::GSIndustryList <- function(){return NativeList([4,5]);};
        ::GSStationList <- function(kind){return NativeList([10,11,12,30,31,32]);};
        ::GSCargoList <- function(){return NativeList([0,1,2]);};
    """)
    for i in range(3):
        vm.execute(f'bridge.services[{i}].dplan="' + str(i + 1) * 64 + '";')
    return vm


@pytest.mark.parametrize(
    "section,offset",
    [("header", 0), ("vehicles", 1), ("map", 64), ("industries", 0), ("stations", 0)],
)
def test_actual_packaged_collector_produces_bounded_correlated_native_pages(section, offset):
    from test_freight_capacity_execution import plain

    vm = packaged_collector_vm()
    q = CanonicalRequest("actual-page", section, offset)
    vm.execute("bridge.Handle(" + q.to_bytes().decode() + ");")
    replies = vm.get_roottable()["replies"]
    raw = json.dumps(plain(replies[len(replies) - 1]), separators=(",", ":")).encode()
    page = CanonicalPage.parse_for(q, raw)
    assert page.restored is True
    assert len(raw) <= 1450
    if section == "header":
        assert page.records[0]["service_plans"] == [str(i + 1) * 64 for i in range(3)]
        assert page.records[0]["vehicle_count"] == 3
    elif section == "vehicles":
        assert page.records[0]["vehicle"] == 2
        assert page.records[0]["owner"] == 0
        assert page.records[0]["orders"][0]["goto_station"] is True
    elif section == "map":
        assert [row["tile"] for row in page.records] == [64, 65, 66, 67]
    elif section == "industries":
        assert page.records[0]["cargo"][0][1] == 25
    elif section == "stations":
        assert page.records[0]["owner"] == 0
        assert page.records[0]["cargo"]


def test_actual_packaged_collector_rejects_partial_restored_service():
    vm = packaged_collector_vm()
    vm.execute("bridge.services[2].dstage=9;")
    with pytest.raises(Exception, match="CANONICAL_SERVICE_STAGE"):
        vm.execute(
            'bridge.Handle({protocol=1,type="canonical-page",request_id="partial",section="header",offset=0});'
        )


def test_actual_packaged_pages_flow_through_full_native_collector(tmp_path, monkeypatch):
    from test_freight_capacity_execution import plain

    from app.simulation.openttd import freight_canonical_save

    vm = packaged_collector_vm()
    vm.execute("""
        ::GSMap=class extends GSMap {
            static function GetMapSizeY(){return 1;}
            static function GetMapSize(){return 64;}
        };
        ::GSGameSettings=class extends GSGameSettings {
            static function GetValue(k){return k=="economy.timekeeping_units"?0:2;}
        };
        ::native_date <- GSDate.GetCurrentDate();
    """)
    date = vm.get_roottable()["native_date"]
    monkeypatch.setattr(
        freight_canonical_save,
        "read_save_clock",
        lambda path: dict(
            date=date,
            date_fract=7,
            economy_date=date,
            economy_date_fract=7,
            tick_counter=456,
            calendar_sub_date_fract=8,
            pause_mode=1,
        ),
    )

    async def exchange(session, q, directory, *, response_type):
        vm.execute("bridge.Handle(" + q.to_bytes().decode() + ");")
        replies = vm.get_roottable()["replies"]
        raw = json.dumps(plain(replies[len(replies) - 1]), separators=(",", ":")).encode()
        (directory / (q.request_id + "-response.json")).write_bytes(raw)
        return response_type.parse_for(q, raw)

    result = asyncio.run(
        collect_canonical(
            None,
            tmp_path,
            identity="packaged-create",
            runtime_sha256="a" * 64,
            bridge_sha256="b" * 64,
            configuration_sha256="c" * 64,
            source_save_sha256="d" * 64,
            snapshot_path=tmp_path / "paused.sav",
            exchange_fn=exchange,
        )
    )
    assert result.state.map["service_plans"] == [str(i + 1) * 64 for i in range(3)]
    assert len(result.state.stations_cargo) == 6
    assert len(result.state.map["tiles"]) == 64
    assert [v.vehicle for v in result.state.vehicles] == [1, 2, 3]
