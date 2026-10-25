"""Controlled offline tests for the D4 native road-corridor wire contract.

The shipped ``d4_corridor_package/main.nut`` runs inside the real Squirrel VM
against a stub road world that reproduces the proven fixed-demo road build
semantics (BuildRoadFull/BuildRoad/BuildRoadStation/BuildRoadDepot, the road
stop and depot front facts and the connected-pair observation); every
dispatched reply is parsed back through the protocol-4 wire contract the
production commanding layer uses, never through the package's own words. Stub
knobs (``::no_op``, ``::quote_reject``, ``::reject``, ``::drift`` and the
funds/quote-cost globals) inject controlled native refusals so the fail-closed
statuses are exercised against the shipped package itself, not against a copy
of the rules. Nothing here launches OpenTTD, connects to an AdminPort or
writes any native or save state: only the tests' own VM world is mutated.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from squirrel import SQVM

from app.simulation.openttd.corridor_construction import (
    CorridorReadback,
    CorridorRequest,
    admit_corridor,
    corridor_phase_outcome,
    verify_corridor,
    verify_corridor_route,
)
from app.simulation.openttd.proof import corridor_construction_native as d4

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "app" / "simulation" / "openttd" / "d4_corridor_package"
API = REPO / "tests" / "fixtures" / "gamescript_api_15.nut"

PRELAUNCH = "a" * 64
OTHER_PLAN = "b" * 64
SOURCE = "c" * 64

MAX_COST = 2000
FLAT_COST = 20  # every quote and every real command in the stub world

# The module's own corridor facts drive every staged pin in the tests, so a
# derivation drift is caught here before any staging: nothing is re-told by hand.
SCHEDULE = d4.corridor_schedule()
ROUTE = d4.route_policy()
WITNESS = tuple(ROUTE["witness_path"])
DEPOT = ROUTE["depot"]
DEPOT_FRONT = ROUTE["depot_front"]


WORLD = """
::dims <- [256, 256];
::tiles <- {};
::road_links <- {};
::road_axis <- {};
::stops <- {};
::depots <- {};
::station_types <- {};
::funds <- 100000;
::tests <- {};
::account <- 0;
::next_station <- 101;
::valid_company <- true;
::second_company <- -1;
::mode_ok <- true;
::cur_company <- 0;
::road_type <- 0;
::road_type_avail <- true;
::reject <- false;
::no_op <- false;
::quote_reject <- false;
::drift <- false;
::quote_cost <- 20;
::exec_cost <- 20;
::test_calls <- 0;
::real_calls <- 0;
::sniffer <- {last = "missing"};
"""

WORLD_SEED = """
function seed(tile, owner=-1, flags=1) {
    ::tiles[tile] <- {flags=flags, owner=owner, industry=null, c={N=1, E=1, W=1, S=1}};
}
/* The whole corridor box: x 172..183, y 174..199 covers both runs, both
 * stops, the corner, the depot pin and its pinned front. */
for (local y = 174; y <= 199; y++) {
    for (local x = 172; x <= 183; x++) {
        seed(y * 256 + x);
    }
}
function stub_abs(v) {
    return v < 0 ? -v : v;
}
function stub_clear_for_road(t) {
    if (!(t in ::tiles) || t in ::stops || t in ::depots) return false;
    local f = ::tiles[t].flags;
    if ((f & (1 << 1)) != 0 || (f & (1 << 2)) != 0 || (f & (1 << 3)) != 0 ||
        (f & (1 << 4)) != 0 || (f & (1 << 5)) != 0 || (f & (1 << 6)) != 0 ||
        (f & (1 << 12)) != 0 || (f & (1 << 13)) != 0) return false;
    local owner = ::tiles[t].owner;
    if (owner != -1 && owner != ::cur_company) return false;
    return true;
}
function stub_link(t) {
    if (!(t in ::road_links)) ::road_links[t] <- {};
}
function stub_roadify(t, axis=null) {
    local f = ::tiles[t];
    /* bit 7 = road transport (IsRoadTile/HasTransportType), bit 9 = the
     * ROADTYPE_ROAD road-type presence bit (HasRoadType(t, 0)). */
    f.flags = f.flags | 0x0080 | 0x0200;
    if (f.owner == -1) f.owner = ::cur_company;
    if (axis != null) ::road_axis[t] <- axis;
    stub_link(t);
}
function stub_is_road(t) {
    return (t in ::tiles) && (::tiles[t].flags & 0x0080) != 0;
}
/* BuildRoadFull: one straight span (axis-safe), each tile clear or already
 * this company's road; the built piece links its consecutive tiles both ways.
 * Real scripted BuildRoadFull builds both straight road bits at both span
 * endpoints, so a collinear adjacent road tile auto-connects at either end. */
function stub_build_road_full(a, b) {
    if (!(a in ::tiles) || !(b in ::tiles)) return false;
    local wx = ::dims[0];
    local dx = (b % wx) - (a % wx);
    local dy = (b / wx) - (a / wx);
    if ((dx != 0 && dy != 0) || stub_abs(dx) + stub_abs(dy) < 1 ||
        stub_abs(dx) + stub_abs(dy) > 36) return false;
    local step = dx == 0 ? wx * (dy < 0 ? -1 : 1) : (dx < 0 ? -1 : 1);
    local axis = dx == 0 ? "y" : "x";
    local count = (dx == 0 ? stub_abs(dy) : stub_abs(dx)) + 1;
    local span = [];
    local tile = a;
    for (local i = 0; i < count; i++) {
        if (!stub_clear_for_road(tile)) return false;
        span.append(tile);
        tile += step;
    }
    foreach (t in span) stub_roadify(t, axis);
    for (local i = 1; i < count; i++) {
        ::road_links[span[i - 1]][span[i]] <- true;
        ::road_links[span[i]][span[i - 1]] <- true;
    }
    /* The full-build endpoints carry both straight bits; connect a collinear
     * adjacent road tile in the outward direction, exactly as native does. */
    local outward_start = span[0] - step;
    local outward_end = span[count - 1] + step;
    if (stub_is_road(outward_start) && (outward_start in ::road_axis) &&
        ::road_axis[outward_start] == axis) {
        ::road_links[span[0]][outward_start] <- true;
        ::road_links[outward_start][span[0]] <- true;
    }
    if (stub_is_road(outward_end) && (outward_end in ::road_axis) &&
        ::road_axis[outward_end] == axis) {
        ::road_links[span[count - 1]][outward_end] <- true;
        ::road_links[outward_end][span[count - 1]] <- true;
    }
    ::funds -= ::exec_cost;
    return true;
}
/* BuildRoad: the one adjacent corner piece bridging two existing fragments. */
function stub_build_road(a, b) {
    if (!(a in ::tiles) || !(b in ::tiles)) return false;
    if (!stub_clear_for_road(a) || !stub_clear_for_road(b)) return false;
    local wx = ::dims[0];
    if (stub_abs((b % wx) - (a % wx)) + stub_abs((b / wx) - (a / wx)) != 1) return false;
    stub_roadify(a);
    stub_roadify(b);
    ::road_links[a][b] <- true;
    ::road_links[b][a] <- true;
    ::funds -= ::exec_cost;
    return true;
}
/* A road stop fronts an existing same-company road fragment (real 15.3 rule). */
function stub_build_road_stop(tile, front) {
    if (!(tile in ::tiles) || !(front in ::tiles)) return false;
    if (tile in ::stops || tile in ::depots) return false;
    if (!stub_clear_for_road(tile)) return false;
    local f = ::tiles[front];
    if (f.owner != ::cur_company || (f.flags & 0x0080) == 0) return false;
    local wx = ::dims[0];
    if (stub_abs((tile % wx) - (front % wx)) + stub_abs((tile / wx) - (front / wx)) != 1)
        return false;
    local sid = ::next_station;
    ::next_station++;
    ::stops[tile] <- {front = front, dt = false, sid = sid};
    ::station_types[sid] <- 0x1;  /* truck stop only */
    ::tiles[tile].flags = ::tiles[tile].flags | 0x4000;
    if (::tiles[tile].owner == -1) ::tiles[tile].owner = ::cur_company;
    stub_link(tile);
    ::road_links[tile][front] <- true;
    ::road_links[front][tile] <- true;
    ::funds -= ::exec_cost;
    return sid;
}
function stub_build_road_depot(tile, front) {
    if (!(tile in ::tiles) || !(front in ::tiles)) return false;
    if (tile in ::stops || tile in ::depots) return false;
    if (!stub_clear_for_road(tile)) return false;
    local f = ::tiles[front];
    if (f.owner != ::cur_company || (f.flags & 0x0080) == 0) return false;
    local wx = ::dims[0];
    if (stub_abs((tile % wx) - (front % wx)) + stub_abs((tile / wx) - (front / wx)) != 1)
        return false;
    ::depots[tile] <- {front = front};
    if (::tiles[tile].owner == -1) ::tiles[tile].owner = ::cur_company;
    stub_link(tile);
    ::road_links[tile][front] <- true;
    ::road_links[front][tile] <- true;
    ::funds -= ::exec_cost;
    return true;
}
/* Drop one interior pair link of a built road piece: a controlled missing
 * road-piece connection the handler must catch before claiming BUILT. */
function stub_drop_last_link(a, b) {
    local wx = ::dims[0];
    local dx = (b % wx) - (a % wx);
    local dy = (b / wx) - (a / wx);
    local step = dx == 0 ? wx * (dy < 0 ? -1 : 1) : (dx < 0 ? -1 : 1);
    local pair0 = b - step;
    local pair1 = b;
    if (pair0 in ::road_links && pair1 in ::road_links) {
        if (pair1 in ::road_links[pair0]) delete ::road_links[pair0][pair1];
        if (pair0 in ::road_links[pair1]) delete ::road_links[pair1][pair0];
    }
}
function last_reply_json() {
    local r = ::replies[::replies.len() - 1];
    local out = "{";
    local first = true;
    foreach (k, v in r) {
        if (typeof k != "string") continue;
        if (!first) out = out + ",";
        first = false;
        out = out + "\\"" + k + "\\":";
        if (v == null) out = out + "null";
        else if (typeof v == "bool") out = out + (v ? "true" : "false");
        else if (typeof v == "string") out = out + "\\"" + v + "\\"";
        else if (typeof v == "array") {
            out = out + "[";
            local afirst = true;
            foreach (item in v) {
                if (!afirst) out = out + ",";
                afirst = false;
                if (item == null) out = out + "null";
                else if (typeof item == "string") out = out + "\\"" + item + "\\"";
                else if (typeof item == "bool") out = out + (item ? "true" : "false");
                else out = out + item;
            }
            out = out + "]";
        }
        else out = out + v;
    }
    return out + "}";
}
"""

STUB = """
class GSCompany {
    static COMPANY_INVALID = -1;
    static function ResolveCompanyID(c) {
        return !::valid_company ? -1 : (c == 0 || c == ::second_company) ? c : -1;
    }
    static function GetBankBalance(_) { return ::funds; }
}
class GSCompanyMode {
    constructor(c) {
        if (c != 0 && c != ::second_company) throw "company";
        ::cur_company = c;
    }
    static function IsValid() { return ::mode_ok; }
}
class GSAccounting {
    constructor() { ::account++; }
    function GetCosts() {
        return (::account in ::tests) ? (::no_op ? 0 : ::quote_cost) : ::exec_cost;
    }
}
class GSTestMode { constructor() { ::tests[::account] <- true; } }
class GSMap {
    static function GetMapSizeX() { return ::dims[0]; }
    static function GetMapSizeY() { return ::dims[1]; }
    static function IsValidTile(t) { return t in ::tiles; }
    static function GetTileX(t) { return t % ::dims[0]; }
    static function GetTileY(t) { return t / ::dims[0]; }
}
class GSTile {
    static TRANSPORT_ROAD = 0;
    static TRANSPORT_RAIL = 1;
    static TRANSPORT_WATER = 2;
    static TRANSPORT_AIR = 3;
    static function b(t, n) { return (::tiles[t].flags & (1 << n)) != 0; }
    static function IsBuildable(t) { return GSTile.b(t, 0); }
    static function IsWaterTile(t) { return GSTile.b(t, 1); }
    static function IsCoastTile(t) { return GSTile.b(t, 2); }
    static function HasTreeOnTile(t) { return GSTile.b(t, 3); }
    static function IsFarmTile(t) { return GSTile.b(t, 4); }
    static function IsRockTile(t) { return GSTile.b(t, 5); }
    static function IsRoughTile(t) { return GSTile.b(t, 6); }
    static function IsHouseTile(t) { return GSTile.b(t, 13); }
    static function IsStationTile(t) { return GSTile.b(t, 14); }
    static function HasTransportType(t, kind) {
        return (kind == 0 && GSTile.b(t, 7)) || (kind == 1 && GSTile.b(t, 10)) ||
               (kind == 2 && GSTile.b(t, 11)) || (kind == 3 && GSTile.b(t, 12));
    }
    static function GetOwner(t) { return ::tiles[t].owner; }
    static function GetMinHeight(t) {
        local a = ::tiles[t].c;
        local mn = a.N;
        if (a.E < mn) mn = a.E;
        if (a.W < mn) mn = a.W;
        if (a.S < mn) mn = a.S;
        return mn;
    }
    static function GetSlope(t) {
        local a = ::tiles[t].c;
        local mn = GSTile.GetMinHeight(t);
        local s = 0;
        if (a.N > mn) s += 8;
        if (a.E > mn) s += 4;
        if (a.W > mn) s += 1;
        if (a.S > mn) s += 2;
        return s;
    }
}
class GSRoad {
    static ROADTYPE_ROAD = 0;
    static ROADVEHTYPE_TRUCK = 0;
    static ROADVEHTYPE_BUS = 1;
    static function SetCurrentRoadType(t) { ::road_type = t; }
    static function GetCurrentRoadType() { return ::road_type; }
    static function IsRoadTypeAvailable(t) { return ::road_type_avail; }
    static function IsRoadTile(t) { return GSTile.b(t, 7); }
    static function HasRoadType(t, i) { return i == 0 && GSTile.b(t, 9); }
    static function AreRoadTilesConnected(t, tile) {
        return t in ::road_links && tile in ::road_links[t];
    }
    static function IsRoadStationTile(t) { return t in ::stops; }
    static function IsDriveThroughRoadStationTile(t) {
        return t in ::stops && ::stops[t].dt;
    }
    static function GetRoadStationFrontTile(t) { return ::stops[t].front; }
    static function IsRoadDepotTile(t) { return t in ::depots; }
    static function GetRoadDepotFrontTile(t) { return ::depots[t].front; }
    static function BuildRoadFull(a, b) {
        if (::account in ::tests) {
            ::test_calls++;
            return ::mode_ok && !::no_op && !::quote_reject;
        }
        ::real_calls++;
        if (::reject) return false;
        if (::drift) {
            local built = stub_build_road_full(a, b);
            if (built) stub_drop_last_link(a, b);
            return built;
        }
        return stub_build_road_full(a, b);
    }
    static function BuildRoad(a, b) {
        if (::account in ::tests) {
            ::test_calls++;
            return ::mode_ok && !::no_op && !::quote_reject;
        }
        ::real_calls++;
        if (::reject) return false;
        return ::drift ? false : stub_build_road(a, b);
    }
    static function BuildRoadStation(tile, front, veh, sid) {
        if (::account in ::tests) {
            ::test_calls++;
            return ::mode_ok && !::no_op && !::quote_reject;
        }
        ::real_calls++;
        if (::reject) return -1;
        return ::drift ? -1 : stub_build_road_stop(tile, front);
    }
    static function BuildRoadDepot(tile, front) {
        if (::account in ::tests) {
            ::test_calls++;
            return ::mode_ok && !::no_op && !::quote_reject;
        }
        ::real_calls++;
        if (::reject) return false;
        return ::drift ? false : stub_build_road_depot(tile, front);
    }
}
class GSStation {
    static STATION_NEW = 0xFE;
    static STATION_TRUCK_STOP = 0x1;
    static STATION_BUS_STOP = 0x2;
    static function GetStationID(t) {
        return t in ::stops ? ::stops[t].sid : -1;
    }
    static function IsValidStation(sid) { return sid >= 0 && (sid in ::station_types); }
    static function HasStationType(sid, type) {
        return sid in ::station_types && (::station_types[sid] & type) != 0;
    }
}
"""


def build_vm(**knobs: int | bool) -> SQVM:
    """Fresh VM with the API fixture, the controlled road world and the package."""
    vm = SQVM()
    vm.execute(API.read_text())
    vm.execute(WORLD)
    if knobs:
        assignments = []
        for name, value in knobs.items():
            literal = str(value).lower() if isinstance(value, bool) else str(value)
            assignments.append(f"::{name} = {literal};")
        vm.execute("\n".join(assignments))
    vm.execute(WORLD_SEED)
    vm.execute(STUB)
    vm.execute((PACKAGE / "main.nut").read_text())
    vm.execute("::bridge <- D4CorridorProof();")
    return vm


def vm_root(vm: SQVM) -> dict[str, Any]:
    return vm.get_roottable()


def drive(vm: SQVM, request: CorridorRequest) -> CorridorReadback:
    """Dispatch one request over the wire and parse the reply into Python."""
    replies = vm_root(vm)["replies"]
    before = len(replies)
    vm.execute("::bridge.Handle(" + request.to_bytes().decode() + ");")
    replies = vm_root(vm)["replies"]
    if len(replies) == before:
        raise AssertionError(f"package dropped request {request.request_id}: no reply")
    vm.execute("::sniffer.last = last_reply_json();")
    raw = vm_root(vm)["sniffer"]["last"]
    assert len(raw) <= 640, f"response for {request.request_id} exceeds 640 bytes"
    return CorridorReadback.parse_for(request, raw.encode())


def build_request(
    op: str,
    entry: dict,
    position: int,
    *,
    plan: str = PRELAUNCH,
    company: int = 0,
    max_cost: int = MAX_COST,
) -> CorridorRequest:
    """The exact production request shapes (same builder the dispatcher uses)."""
    if op == "inspect":
        request_id = f"inspect-{position:02d}"
    elif op == "read":
        request_id = f"confirm-{position:02d}"
    else:
        request_id = f"{op}-{position:02d}"
    return d4._corridor_request(
        op, request_id, plan, company, max_cost, dict(entry)
    )


def inspect_of(entry: dict, position: int) -> CorridorRequest:
    return build_request("inspect", entry, position)


def command_of(entry: dict, position: int) -> CorridorRequest:
    return build_request(entry["kind"], entry, position)


def read_of(entry: dict, position: int) -> CorridorRequest:
    return build_request("read", entry, position)


def admit(entry: dict, position: int, before: CorridorReadback):
    """The production admission (same gate the dispatcher runs at launch)."""
    return admit_corridor(
        before,
        prelaunch_digest=PRELAUNCH,
        source_save_digest=SOURCE,
        staged_run_len=entry.get("run_len"),
        max_cost=MAX_COST,
    )


def run_group(vm: SQVM, entry: dict, position: int) -> tuple:
    """One op's full exchange group (inspect -> command -> read), verified."""
    before = drive(vm, inspect_of(entry, position))
    intent = admit(entry, position, before)
    built = drive(vm, command_of(entry, position))
    independent = drive(
        vm,
        read_of(entry, position).model_copy(update={"plan": intent.digest}),
    )
    verify_corridor(intent, before, built, independent)
    return intent, dict(
        intent=intent, before=before, built=built, independent=independent
    )


def run_phase(vm: SQVM) -> list[tuple[str, dict]]:
    """The whole staged phase: len(SCHEDULE) * 3 exchanges in the staged order."""
    attempts = []
    for position, entry in enumerate(SCHEDULE):
        _, evidence = run_group(vm, entry, position)
        attempts.append((f"op-{entry['index']:02d}", evidence))
    return attempts


def route_read(vm: SQVM) -> dict:
    """The final pure-observation route read, verified by production code."""
    request = CorridorRequest(
        op="route",
        request_id="route-00",
        plan=PRELAUNCH,
        company=0,
        max_cost=0,
        tiles=WITNESS,
    )
    readback = drive(vm, request)
    receipt = verify_corridor_route(
        readback,
        prelaunch_digest=PRELAUNCH,
        expected_pairs=ROUTE["expected_pairs"],
        expected_path=WITNESS,
    )
    assert receipt["verification"] == "ROUTE_VERIFIED"
    return receipt


# --- the corridor happy path: seven built ops and the route read --------------


def test_setup_pins_stay_derived_not_retold():
    """The test world's pins equal the module's own staged derivation."""
    assert SCHEDULE[0]["start"] == 45747 and SCHEDULE[0]["end"] == 45743
    assert SCHEDULE[0]["run_len"] == 5
    assert SCHEDULE[1]["start"] == 45999 and SCHEDULE[1]["end"] == 48047
    assert SCHEDULE[1]["run_len"] == 9
    assert SCHEDULE[2]["start"] == 48303 and SCHEDULE[2]["end"] == 50095
    assert SCHEDULE[2]["run_len"] == 8
    assert (SCHEDULE[3]["start"], SCHEDULE[3]["end"]) == (45743, 45999)
    assert (SCHEDULE[4]["tile"], SCHEDULE[4]["front"]) == (45748, 45747)
    assert (SCHEDULE[5]["tile"], SCHEDULE[5]["front"]) == (50351, 50095)
    assert (DEPOT, DEPOT_FRONT) == (45487, 45743)
    assert ROUTE["expected_pairs"] == len(WITNESS) - 1 == 23
    assert all(
        (entry.get("start"), entry.get("end")) != (48047, 48303)
        for entry in SCHEDULE
    )


def test_full_phase_reaches_a_connected_usable_route():
    """The staged ops admit, build and read in order through the production
    verifiers; the route read then proves the connected usable corridor."""
    vm = build_vm()
    attempts = run_phase(vm)
    assert [label for label, _ in attempts] == [f"op-{i:02d}" for i in range(7)]
    phase = corridor_phase_outcome(attempts)
    assert phase["verification"] == "PHASE_COMPLETE"
    assert phase["failed"] is None and phase["pending"] == []
    assert len(phase["completed"]) == 7
    for receipt in phase["completed"]:
        assert receipt["verification"] == "NATIVE_STATE_CHANGED"
        assert 0 < receipt["cost"] <= MAX_COST
        assert receipt["prelaunch_digest"] == PRELAUNCH
        assert receipt["source_save_digest"] == SOURCE
        assert receipt["error_code"] is None
    route = route_read(vm)
    assert route["connected_pairs"] == 23 and route["first_fail_index"] == -1
    assert route["cost"] == 0


def test_route_read_reports_the_observed_facts_precisely():
    """The route read is pure observation: it fixes the counted pairs, both
    stop facts and the depot pin, and its funds are the same world's."""
    vm = build_vm()
    run_phase(vm)
    request = CorridorRequest(
        op="route",
        request_id="route-00",
        plan=PRELAUNCH,
        company=0,
        max_cost=0,
        tiles=WITNESS,
    )
    readback = drive(vm, request)
    assert readback.connected_pairs == 23 and readback.first_fail == -1
    assert readback.pickup_stop is True and readback.delivery_stop is True
    assert readback.pickup_sid is not None and readback.pickup_sid >= 0
    assert readback.delivery_sid is not None and readback.delivery_sid >= 0
    assert readback.pickup_sid != readback.delivery_sid
    assert readback.depot_pin_ok is True
    assert readback.cost == 0
    assert readback.funds == 100000 - len(SCHEDULE) * FLAT_COST


def test_collinear_full_runs_auto_connect_but_the_corner_still_needs_its_join():
    """Candidate-3 regression: scripted BuildRoadFull builds both straight
    road bits at both span endpoints, so the collinear run-B segments are
    already connected at the interior pair. The perpendicular corner is not
    connected and remains a real join op; scheduling the interior pair is
    redundant and makes admission return NOT_BUILDABLE."""
    vm = build_vm()
    run_group(vm, SCHEDULE[0], 0)
    run_group(vm, SCHEDULE[1], 1)
    later = drive(vm, command_of(SCHEDULE[4], 4))
    assert later.status == "OUT_OF_ORDER"
    run_group(vm, SCHEDULE[2], 2)
    vm.execute("::linked_interior <- ::bridge.Linked(48047, 48303);")
    assert vm_root(vm)["linked_interior"] is True
    vm.execute(
        "::interior_obs <- ::bridge.ObserveRoad(48047, 48303, 0);"
        "::interior_eligible <- ::bridge.Eligible(\"road\", 0, ::interior_obs);"
    )
    interior_obs = vm_root(vm)["interior_obs"]
    assert interior_obs["covered"] == 2 and interior_obs["pairs_ok"] == 1
    assert vm_root(vm)["interior_eligible"] is False
    pre = drive(vm, inspect_of(SCHEDULE[3], 3))
    assert pre.target == "road"
    assert pre.owner0 == 0 and pre.owner1 == 0
    assert pre.road0 is True and pre.road1 is True
    assert pre.covered == 2 and pre.pairs_ok == 0
    assert pre.pair_total == 1
    intent = admit(SCHEDULE[3], 3, pre)
    assert intent.run_len == 2
    built = drive(vm, command_of(SCHEDULE[3], 3))
    assert built.status == "BUILT"
    assert built.pairs_ok == built.pair_total == 1
    assert built.cost == pre.cost


# --- controlled native refusals (fail-closed statuses) ------------------------


def test_zero_cost_quote_is_a_terminal_admission_refusal():
    """The stub's zero-cost test quote can never trigger any command."""
    vm = build_vm(no_op=True)
    entry, position = SCHEDULE[0], 0
    before = drive(vm, inspect_of(entry, position))
    assert before.status == "REJECTED"
    assert before.eligible is True and before.cost == 0
    with pytest.raises(ValueError, match="positive tested cost"):
        admit(entry, position, before)
    assert vm_root(vm)["real_calls"] == 0


def test_quote_reject_refuses_admission_without_a_command():
    vm = build_vm(quote_reject=True)
    before = drive(vm, inspect_of(SCHEDULE[0], 0))
    assert before.status == "REJECTED"
    assert vm_root(vm)["real_calls"] == 0


def test_insufficient_funds_refuses_inspection():
    vm = build_vm()
    vm_root(vm)["funds"] = 10
    before = drive(vm, inspect_of(SCHEDULE[0], 0))
    assert before.status == "INSUFFICIENT_FUNDS"
    assert vm_root(vm)["real_calls"] == 0


def test_over_ceiling_quote_reports_cost_limit():
    vm = build_vm()
    vm_root(vm)["quote_cost"] = 3000
    before = drive(vm, inspect_of(SCHEDULE[0], 0))
    assert before.status == "COST_LIMIT"
    assert vm_root(vm)["real_calls"] == 0


def test_quote_cost_drift_between_admission_and_execution():
    """A re-quote that differs from the admitted cost never runs a command."""
    vm = build_vm()
    entry, position = SCHEDULE[0], 0
    before = drive(vm, inspect_of(entry, position))
    assert before.status == "READY"
    intent = admit(entry, position, before)
    vm_root(vm)["quote_cost"] = 30
    built = drive(vm, command_of(entry, position))
    assert built.status == "COST_CHANGED"
    assert vm_root(vm)["real_calls"] == 0
    with pytest.raises(ValueError, match="construction result"):
        verify_corridor(
            intent, before, built,
            drive(vm, read_of(entry, position).model_copy(update={"plan": intent.digest})),
        )


def test_halted_command_preserves_the_verified_prefix():
    """A rejected real command halts the phase: nothing later dispatches and
    the world state stays explicitly uncertain (no compensating runs)."""
    vm = build_vm(reject=True)
    attempts = []
    failed_seen = False
    for position, entry in enumerate(SCHEDULE):
        label = f"op-{entry['index']:02d}"
        if failed_seen:
            attempts.append((label, dict()))
            continue
        try:
            _, evidence = run_group(vm, entry, position)
            attempts.append((label, evidence))
        except Exception as error:
            attempts.append((label, dict(failed=f"{type(error).__name__}: {error}")))
            failed_seen = True
    failed = [label for label, evidence in attempts if "failed" in evidence]
    assert failed == ["op-00"]
    phase = corridor_phase_outcome(attempts)
    assert phase["verification"] == "PARTIAL_EXECUTION_EVIDENCE"
    assert phase["failed"]["label"] == "op-00"
    assert phase["pending"] == [f"op-{i:02d}" for i in range(1, len(SCHEDULE))]
    later = drive(vm, command_of(SCHEDULE[1], 1))
    assert later.status == "OUT_OF_ORDER"
    assert vm_root(vm)["real_calls"] == 1  # exactly the one failed build call


def test_partial_native_build_reports_readback_mismatch_not_built():
    """The stub builds the span but drops one link: the handler must refuse
    BUILT (READBACK_MISMATCH) and never claim the missing piece."""
    vm = build_vm()
    vm_root(vm)["drift"] = True
    entry, position = SCHEDULE[0], 0
    before = drive(vm, inspect_of(entry, position))
    intent = admit(entry, position, before)
    built = drive(vm, command_of(entry, position))
    assert built.status == "READBACK_MISMATCH"
    assert built.owner0 == 0 and built.owner1 == 0
    assert built.covered == built.run_len
    assert built.pairs_ok == built.pair_total - 1
    independent = drive(
        vm, read_of(entry, position).model_copy(update={"plan": intent.digest})
    )
    assert independent.status == "READ"
    assert independent.pairs_ok == independent.pair_total - 1
    with pytest.raises(ValueError, match="construction result"):
        verify_corridor(intent, before, built, independent)


def test_out_of_order_commands_never_dispatch_before_their_stage():
    vm = build_vm()
    later = drive(vm, command_of(SCHEDULE[1], 1))
    assert later.status == "OUT_OF_ORDER"
    corner = drive(vm, command_of(SCHEDULE[3], 3))
    assert corner.status == "OUT_OF_ORDER"
    assert vm_root(vm)["real_calls"] == 0


def test_command_without_fresh_admission_is_stale():
    vm = build_vm()
    stale = drive(vm, command_of(SCHEDULE[0], 0))
    assert stale.status == "STALE_ADMISSION"
    assert vm_root(vm)["real_calls"] == 0


def test_admitted_plan_drift_blocks_the_command():
    """A command request carrying a plan other than the latched admission seal
    must never run; the handler compares it at the mutation boundary."""
    vm = build_vm()
    entry, position = SCHEDULE[0], 0
    before = drive(vm, inspect_of(entry, position))
    admit(entry, position, before)
    drift = drive(vm, command_of(entry, position).model_copy(update={"plan": OTHER_PLAN}))
    assert drift.status == "STALE_ADMISSION"
    assert vm_root(vm)["real_calls"] == 0


def test_duplicate_command_is_already_attempted():
    vm = build_vm()
    run_group(vm, SCHEDULE[0], 0)
    duplicate = drive(
        vm, command_of(SCHEDULE[0], 0).model_copy(update={"request_id": "full-90"})
    )
    assert duplicate.status == "ALREADY_ATTEMPTED"


def test_unknown_company_is_refused_before_any_native_fact():
    vm = build_vm()
    request = command_of(SCHEDULE[0], 0).model_copy(update={"company": 5})
    reply = drive(vm, request)
    assert reply.status == "INVALID_COMPANY"
    assert reply.owner0 is None and reply.run_len is None


def test_read_is_intent_scoped_observation():
    """The independent read carries the admitted intent digest and only ever
    reports the observed post-state of its staged pins."""
    vm = build_vm()
    for position in range(4):
        run_group(vm, SCHEDULE[position], position)
    entry, position = SCHEDULE[4], 4
    before = drive(vm, inspect_of(entry, position))
    intent = admit(entry, position, before)
    built = drive(vm, command_of(entry, position))
    assert built.status == "BUILT" and built.sid >= 0
    readback = drive(
        vm, read_of(entry, position).model_copy(update={"plan": intent.digest})
    )
    verify_corridor(intent, before, built, readback)
    drifted = drive(
        vm,
        read_of(entry, position).model_copy(
            update={"plan": SOURCE, "request_id": "confirm-93"}
        ),
    )
    with pytest.raises(ValueError, match="independent readback"):
        verify_corridor(intent, before, built, drifted)


def test_station_post_state_and_front_ownership():
    """The truck stop reports its station id and its pinned front owner."""
    vm = build_vm()
    for position in range(4):
        run_group(vm, SCHEDULE[position], position)
    intent, evidence = run_group(vm, SCHEDULE[4], 4)
    built = evidence["built"]
    assert built.stop is True and built.truck is True
    assert built.drive_through is False and built.depot is False
    assert built.sid >= 0 and 0 < built.cost <= MAX_COST
    assert built.front_owner == 0 and built.linked is True
    prod = verify_corridor(intent, evidence["before"], built, evidence["independent"])
    assert prod["kind"] == "station" and prod["operation"] == "ROAD_STATION"


def test_depot_post_state_binds_its_pinned_front():
    """The depot reports the exact front id and the front ownership rule."""
    vm = build_vm()
    for position in range(6):
        run_group(vm, SCHEDULE[position], position)
    intent, evidence = run_group(vm, SCHEDULE[6], 6)
    built = evidence["built"]
    assert built.depot is True and built.depot_front_id == DEPOT_FRONT
    assert built.depot_linked is True and built.front_owner == 0
    assert built.stop is False and built.truck is False
    prod = verify_corridor(intent, evidence["before"], built, evidence["independent"])
    assert prod["kind"] == "depot" and prod["operation"] == "ROAD_DEPOT"
    assert json.dumps(prod["pins"]) == json.dumps(
        dict(start=None, end=None, tile=DEPOT, front=DEPOT_FRONT, tiles=None)
    )


def test_delivery_stop_after_the_last_run_segment():
    """The delivery stop course (fronts run B's last road tile) verifies the
    same way as the pickup stop, over the module's own pins."""
    vm = build_vm()
    for position in range(5):
        run_group(vm, SCHEDULE[position], position)
    intent, evidence = run_group(vm, SCHEDULE[5], 5)
    built = evidence["built"]
    assert built.stop is True and built.stop_owner == 0
    assert built.front == SCHEDULE[5]["front"] == 50095
    assert built.front_owner == 0 and built.linked is True
    verify_corridor(intent, evidence["before"], built, evidence["independent"])


def test_responses_never_exceed_the_512_byte_bound():
    """Every staged exchange reply parses through the same 512-byte gate the
    secure session enforces; the route read is the largest and stays small."""
    vm = build_vm()
    run_phase(vm)
    route_read(vm)
    assert (
        len(vm_root(vm)["replies"]) == d4.PLANNED_CORRIDOR_REQUESTS == 22
    )


def test_dispatcher_budget_refuses_the_request_after_the_cap():
    """The 22 planned exchanges fill the planned budget; six slack reads use
    up the 6-request slack and the next request after the 28-request cap is
    dropped without any reply (never re-labelled or reordered), unique ids
    only so the refusal is the dispatcher's cap, not the duplicate rule."""
    vm = build_vm()
    run_phase(vm)
    route_read(vm)
    for position in range(90, 96):
        reply = drive(vm, read_of(SCHEDULE[0], position))
        assert reply.status == "READ"
    vm.execute("::sniffer.requests <- ::bridge.requests;")
    assert vm_root(vm)["sniffer"]["requests"] == d4.CORRIDOR_REQUEST_BUDGET == 28
    with pytest.raises(AssertionError, match="dropped request"):
        drive(vm, read_of(SCHEDULE[0], 96))


def test_gamescript_stage_keys_track_the_staged_schedule():
    """The shipped package's baked StageIndex keys equal the schedule
    derivation's own kind/pin keys in execution order: an offline read of the
    package text catches any staged-op drift before any VM launch."""
    text = (PACKAGE / "main.nut").read_text()
    span = re.search(r"local stages = \[([^\]]*)\]", text)
    assert span is not None
    keys = []
    entries = re.findall(
        r'(ShapeKey|KindKey)\("(\w+)",\s*(\d+)(?:,\s*(\d+))?\)', span.group(1)
    )
    for fn, kind, first, second in entries:
        if fn == "ShapeKey":
            lo, hi = sorted((int(first), int(second)))
            keys.append(f"{kind}-{lo}-{hi}")
        else:
            keys.append(f"{kind}-{first}")
    expected = []
    for entry in SCHEDULE:
        if "tile" in entry:
            expected.append(f"{entry['kind']}-{entry['tile']}")
        else:
            lo, hi = sorted((entry["start"], entry["end"]))
            expected.append(f"{entry['kind']}-{lo}-{hi}")
    assert keys == expected
    assert len(keys) == 7 == d4.ROAD_OP_COUNT
