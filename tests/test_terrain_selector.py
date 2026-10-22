"""Native-startup selector regression through the production Squirrel handler."""

import json
import os
import subprocess

import pytest
from squirrel import SQVM

from app.simulation.openttd.supplemental_planning_facts import Region
from app.simulation.openttd.tile_facts import (
    TileFactsExchange,
    TileFactsReceipt,
    TileFactsRequest,
)
from tests.test_terrain_query import gs_request, vm_source, wire_value


def request():
    return TileFactsRequest("terrain-single-page-review", Region(x=1, y=1, width=5, height=1), 0)


@pytest.mark.parametrize("initial", [0, 1, 63])
def test_selector_established_before_five_tile_reads(initial):
    vm = SQVM()
    vm.execute(vm_source())
    vm.execute(f"::width=64; ::height=64; ::current={initial};")
    q = request()
    vm.execute("::b <- NoMutationBridge(); b.Handle(" + gs_request(q) + ");")
    root = vm.get_roottable()
    response = wire_value(root["replies"][0])
    assert response.get("status") == "ok", response
    payload = json.dumps(response, sort_keys=True, separators=(",", ":")).encode()
    exchange = TileFactsExchange(
        q.to_bytes(), payload, TileFactsReceipt.correlate(q.to_bytes(), payload)
    )
    exchange.validate()
    assert [row[0] for row in exchange.response.rows] == [65, 66, 67, 68, 69]
    assert len(payload) <= 420 and len(q.to_bytes()) == 111
    assert root["current"] == 0 and root["selector_sets"] == 1
    assert wire_value(root["selector_events"]) == ["available", "set", "get"]
    assert root["calls"] <= 226


@pytest.mark.parametrize("change", ["::available=false;", "::setter_refuses=true;"])
def test_selector_failure_precedes_tile_reads(change):
    vm = SQVM()
    vm.execute(vm_source())
    vm.execute(change)
    vm.execute("::b <- NoMutationBridge(); b.Handle(" + gs_request(request()) + ");")
    root = vm.get_roottable()
    response = wire_value(root["replies"][0])
    assert response["status"] == "error"
    assert response["error_code"] == "UNSUPPORTED_ROAD_TYPE"
    assert response["failed_tile"] is None
    assert root["calls"] <= 4
    assert root["selector_sets"] == (0 if "available" in change else 1)


@pytest.mark.parametrize(
    "initial,change,error",
    [
        (63, "", False),
        (0, "", False),
        (1, "", False),
        (63, "::available=false;", True),
        (63, "::setter_refuses=true;", True),
    ],
)
def test_tagged_startup_selector_path(tmp_path, initial, change, error):
    exe = os.environ.get("TILE_FACTS_SERIALIZER_PROBE")
    if not exe:
        pytest.skip("tagged offline serializer VM not configured")
    q = request()
    script = tmp_path / "startup.nut"
    script.write_text(
        vm_source()
        + '\nif(::current!=63)throw "startup";\n'
        + f"::current={initial};\n{change}\n::width=64; ::height=64;\n"
        + "local b=NoMutationBridge(); b.Handle("
        + gs_request(q)
        + ");\n"
        + (
            'if(::calls>4 || ::replies[0].failed_tile!=null)throw "early failure";'
            if error
            else 'if(::current!=0 || ::selector_sets!=1)throw "selection";'
        )
    )
    result = subprocess.run([exe, str(script)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    payload = next(
        line[5:] for line in result.stdout.splitlines() if line.startswith("JSON ")
    ).encode()
    if error:
        response = json.loads(payload)
        assert response["status"] == "error" and response["error_code"] == "UNSUPPORTED_ROAD_TYPE"
        assert len(payload) <= 227
        return
    exchange = TileFactsExchange(
        q.to_bytes(), payload, TileFactsReceipt.correlate(q.to_bytes(), payload)
    )
    exchange.validate()
    assert tuple(row[0] for row in exchange.response.rows) == (65, 66, 67, 68, 69)
    assert len(payload) <= 420


def test_every_operation_reestablishes_selector():
    vm = SQVM()
    vm.execute(vm_source())
    call = "b.Handle(" + gs_request(request()) + ");"
    vm.execute("::b <- NoMutationBridge(); " + call + "::current=1; " + call)
    root = vm.get_roottable()
    assert root["current"] == 0 and root["selector_sets"] == 2
    assert all(response["status"] == "ok" for response in wire_value(root["replies"]))


@pytest.mark.parametrize("kind", ["none", "road", "tram", "custom_road"])
def test_occupancy_preserved_after_selection(kind):
    vm = SQVM()
    vm.execute(vm_source())
    if kind != "none":
        vm.execute(f"::{kind}=true;")
    q = request()
    vm.execute("::b <- NoMutationBridge(); b.Handle(" + gs_request(q) + ");")
    payload = json.dumps(wire_value(vm.get_roottable()["replies"][0])).encode()
    exchange = TileFactsExchange(
        q.to_bytes(), payload, TileFactsReceipt.correlate(q.to_bytes(), payload)
    )
    for row, fact in zip(exchange.response.rows, exchange.response.tiles, strict=True):
        assert fact.road == (kind != "none")
        assert row[6] == (1 if kind == "road" else 0)
        if kind in ("tram", "custom_road"):
            assert not fact.buildable
            assert row[7] == row[8] == 0
    if kind == "road":
        assert exchange.response.rows[0][7:9] == (2, 0)
        assert exchange.response.rows[1][7:9] == (2, 8)


@pytest.mark.parametrize(
    "change,code,tile",
    [
        ("::width=64; ::height=64; ::void_tile=65;", "INVALID_TILE", 65),
        ("::getter_failure=true;", "BRIDGE_FAILURE", None),
        ("::slope=65535;", "UNSUPPORTED_NATIVE_FACT", 4097),
        ("::available=1;", "UNSUPPORTED_ROAD_TYPE", None),
        ("::current=-1; ::setter_refuses=true;", "UNSUPPORTED_ROAD_TYPE", None),
        ("::current=0.0; ::setter_refuses=true;", "UNSUPPORTED_ROAD_TYPE", None),
    ],
)
def test_unknown_getters_and_selector_fail_closed(change, code, tile):
    vm = SQVM()
    vm.execute(vm_source())
    vm.execute(change)
    vm.execute("::b <- NoMutationBridge(); b.Handle(" + gs_request(request()) + ");")
    response = wire_value(vm.get_roottable()["replies"][0])
    assert response["status"] == "error" and response["error_code"] == code
    assert response["failed_tile"] == tile
