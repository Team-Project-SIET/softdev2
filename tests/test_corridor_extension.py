"""Controlled offline tests for the D5 native corridor-extension wire contract.

The shipped ``d5_extension_package/main.nut`` extends the built D4 corridor:
a vertical full run east of the delivery front (50096..50864), the horizontal
join 50095-50096 and a new truck stop 50863 fronting 50864, each executed at
most once. The package runs inside the real Squirrel VM against a stub road
world that pre-plants the proven D4 corridor (runs, stops, depot) and models
the retained census facts south of the delivery stop; every dispatched reply
is parsed back through the protocol-4 wire contract the production commanding
layer uses, never through the package's own words. Stub knobs (``::no_op``,
``::quote_reject``, ``::reject``, ``::pre_ext_stop`` and the funds/quote-cost
globals) inject controlled native refusals so the fail-closed statuses are
exercised against the shipped package itself. Nothing here launches OpenTTD,
connects to an AdminPort or writes any native or save state: only the tests'
own VM world is mutated.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from squirrel import SQVM

from app.simulation.openttd.corridor_construction import (
    MAX_CORRIDOR_RESPONSE_BYTES,
    CorridorReadback,
    CorridorRequest,
    admit_corridor,
    corridor_phase_outcome,
    verify_corridor,
    verify_corridor_route,
)
from app.simulation.openttd.proof import corridor_construction_native as d4

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "app" / "simulation" / "openttd" / "d5_extension_package"
API = REPO / "tests" / "fixtures" / "gamescript_api_15.nut"

PRELAUNCH = "a" * 64
OTHER_PLAN = "b" * 64
SOURCE = "c" * 64

MAX_COST = 2000

# The staged exchange groups carry their own pinned native quotes (the D4
# corridor holds its historical per-piece pricing; the extension ops quote
# the branch pieces explicitly).
OP_COSTS = {0: 454, 1: 71, 2: 307}

# The built D4 corridor (OpenTTD 15.3 Seed-17, 256x256, tile = y*256+x), the
# pinned extension design facts: the branch full run occupies vacant unowned
# roadless flat ground south of the delivery stop's front, the tie-in runs to
# the delivery front tile, and the branch stop fronts the branch end.
SCHEDULE = [
    dict(index=0, kind="full", start=50096, end=50864, run_len=4),
    dict(index=1, kind="road", start=50095, end=50096, run_len=2),
    dict(index=2, kind="station", tile=50863, front=50864, run_len=None),
]
BRANCH_RUN = (50096, 50352, 50608, 50864)
BRANCH_FRONT = 50095
EXT_STOP = 50863
EXT_FRONT = 50864
PICKUP = 45748
PICKUP_FRONT = 45747
DEPOT = 45487
DEPOT_FRONT = 45743

# The 30-tile ordered witness path of the extended corridor. It retraces
# 50095 past the dead-end delivery stop 50351 so the stop pair is witnessed
# twice by design; only consecutive-pair connectivity is checked.
WITNESS = (
    45748,
    45747,
    45746,
    45745,
    45744,
    45743,
    45999,
    46255,
    46511,
    46767,
    47023,
    47279,
    47535,
    47791,
    48047,
    48303,
    48559,
    48815,
    49071,
    49327,
    49583,
    49839,
    50095,
    50351,
    50095,
    50096,
    50352,
    50608,
    50864,
    50863,
)
EXPECTED_ROUTE_PAIRS = len(WITNESS) - 1

PLANNED_REQUESTS = len(SCHEDULE) * 3 + 1  # 10
REQUEST_BUDGET = PLANNED_REQUESTS + 6  # 16: request 17 is the first refused


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
::next_station <- 0;
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
::pre_ext_stop <- false;
::quote_cost <- 20;
::exec_cost <- 20;
::test_calls <- 0;
::real_calls <- 0;
::station_calls <- [];
::sniffer <- {last = "missing"};
"""

WORLD_SEED = """
function seed(tile, owner=-1, flags=1) {
    ::tiles[tile] <- {flags=flags, owner=owner, industry=null, c={N=1, E=1, W=1, S=1}};
}
/* The corridor box: x 172..183, y 174..199 covers the built D4 corridor, the
 * pinned depot and its front, and the whole branch geometry south and east
 * of the delivery front (warehouse-vacant flat census ground). */
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
/* BuildRoad: the one adjacent piece bridging two existing fragments. */
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
/* Seed the untouched built D4 corridor the extension ties into: run A
 * 45747..45743 (x 175..179, y 178), both collinear run-B segments
 * 45999..48047 and 48303..50095 (x 175, y 179..195) which auto-connect at
 * 48047-48303, the perpendicular corner 45743-45999, the pickup stop 45748
 * on its front 45747, the delivery stop 50351 on its front 50095 and the
 * depot 45487 fronting 45743. Station ids are handed out from 0, so the
 * corridor stops own sid 0 and sid 1 and the extension station gets sid 2. */
::cur_company <- 0;
stub_build_road_full(45747, 45743);
stub_build_road_full(45999, 48047);
stub_build_road_full(48303, 50095);
stub_build_road(45743, 45999);
stub_build_road_stop(45748, 45747);
stub_build_road_stop(50351, 50095);
stub_build_road_depot(45487, 45743);
/* An optional occupied stop-tile fixture (the extension stop tile already
 * carries a stop, e.g. a prior survey artifact). */
if (::pre_ext_stop) {
    ::stops[50863] <- {front = 50864, dt = false, sid = 2};
    ::station_types[2] <- 0x1;
    ::tiles[50863].flags = ::tiles[50863].flags | 0x4000;
    ::tiles[50863].owner = 0;
    ::next_station = 3;
}
::tiles[50863].c = {N=1, E=1, W=1, S=1};
/* The D5-TERRAIN-SURVEY-1 receipts of record, live on this world: the
 * escarpment ramp tiles 50096 and 50352 measured live slope 12 (N|E
 * raised, min 1 max 2), 50608 live slope 8 (N raised alone), and the
 * stop-front pair 50863/50864 measured live-flat height 1 — exactly the
 * corner model the survey-bound gate observes. */
::tiles[50096].c = {N=2, E=2, W=1, S=1};
::tiles[50352].c = {N=2, E=2, W=1, S=1};
::tiles[50608].c = {N=2, E=1, W=1, S=1};
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
        return (::drift) ? false : stub_build_road(a, b);
    }
    static function BuildRoadStation(tile, front, veh, sid) {
        ::station_calls.append([tile, front, veh, sid]);
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
        vm.execute("\n".join(assignments))  # knob assignment precedes seeding
    vm.execute(WORLD_SEED)
    vm.execute(STUB)
    vm.execute((PACKAGE / "main.nut").read_text())
    vm.execute("::bridge <- NetworkFreightProof();")
    return vm


def vm_root(vm: SQVM) -> dict[str, Any]:
    return vm.get_roottable()


def seed_funds(vm: SQVM) -> int:
    """The world balance after the D4 corridor pre-plant (7 stub builds)."""
    return vm_root(vm)["funds"]


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
    assert len(raw) <= MAX_CORRIDOR_RESPONSE_BYTES, (
        f"response for {request.request_id} exceeds {MAX_CORRIDOR_RESPONSE_BYTES} bytes"
    )
    return CorridorReadback.parse_for(request, raw.encode())


def silently_dropped(vm: SQVM, request: CorridorRequest) -> None:
    before = len(vm_root(vm)["replies"])
    vm.execute("::bridge.Handle(" + request.to_bytes().decode() + ");")
    assert len(vm_root(vm)["replies"]) == before  # dropped without any reply


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
    return d4._corridor_request(op, request_id, plan, company, max_cost, dict(entry))


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


def set_cost(vm: SQVM, position: int) -> None:
    """Pin the stub quote/execution cost to the staged op's native price."""
    cost = OP_COSTS[position]
    for name in ("quote_cost", "exec_cost"):
        vm_root(vm)[name] = cost


def run_group(vm: SQVM, entry: dict, position: int) -> tuple:
    """One op's full exchange group (inspect -> command -> read), verified."""
    set_cost(vm, position)
    before = drive(vm, inspect_of(entry, position))
    intent = admit(entry, position, before)
    built = drive(vm, command_of(entry, position))
    independent = drive(
        vm,
        read_of(entry, position).model_copy(update={"plan": intent.digest}),
    )
    verify_corridor(intent, before, built, independent)
    return intent, dict(intent=intent, before=before, built=built, independent=independent)


def run_phase(vm: SQVM) -> list[tuple[str, dict]]:
    """The whole staged phase: 3 ops x 3 exchanges in the staged order."""
    attempts = []
    for position, entry in enumerate(SCHEDULE):
        _, evidence = run_group(vm, entry, position)
        attempts.append((f"op-{entry['index']:02d}", evidence))
    return attempts


def route_request(
    vm: SQVM,
    *,
    request_id: str = "route-00",
    tiles: tuple[int, ...] = WITNESS,
) -> CorridorRequest:
    return CorridorRequest(
        op="route",
        request_id=request_id,
        plan=PRELAUNCH,
        company=0,
        max_cost=0,
        tiles=tiles,
    )


def route_read(vm: SQVM, **kwargs) -> dict:
    """The final pure-observation route read, verified by production code."""
    request = route_request(vm, **kwargs)
    readback = drive(vm, request)
    receipt = verify_corridor_route(
        readback,
        prelaunch_digest=PRELAUNCH,
        expected_pairs=len(request.tiles) - 1 if "tiles" not in kwargs else EXPECTED_ROUTE_PAIRS,
        expected_path=tuple(request.tiles),
    )
    assert receipt["verification"] == "ROUTE_VERIFIED"
    return receipt


# --- the shipped package's baked schedule stays pinned offline ---------------


def test_baked_stage_keys_track_the_extension_schedule():
    """The shipped package's baked StageIndex keys equal the staged extension
    pins exactly, in execution order: an offline read of the package text
    catches any staged-op drift before any VM launch."""
    text = (PACKAGE / "main.nut").read_text()
    span = re.search(r"local stages = \[([^\]]*)\]", text)
    assert span is not None
    keys = []
    entries = re.findall(r'(ShapeKey|KindKey)\("(\w+)",\s*(\d+)(?:,\s*(\d+))?\)', span.group(1))
    for fn, kind, first, second in entries:
        if fn == "ShapeKey":
            lo, hi = sorted((int(first), int(second)))
            keys.append(f"{kind}-{lo}-{hi}")
        else:
            keys.append(f"{kind}-{first}")
    assert keys == [
        "full-50096-50864",
        "road-50095-50096",
        "station-50863",
    ]
    assert "extends D5CorridorExtensionProof" in text
    assert "class D5CorridorExtensionProof" in text
    assert 'GSLog.Info("D5_EXT_READY")' in text
    assert 'GSLog.Info("D4_' not in text
    assert "D4CorridorProof" not in text
    assert "GSStation.STATION_NEW" in text
    assert re.search(r"max_requests = 16\b", text)
    assert "EXT_STOP = 50863" in text and "EXT_FRONT = 50864" in text
    assert "BRANCH_RUN = [50096, 50864]" in text
    assert "BRANCH_JOIN = [50095, 50096]" in text
    assert not re.search(r"\bDELIVERY\b =", text)


def test_setup_pins_stay_derived_not_retold():
    """The staged extension facts are the pinned design facts themselves."""
    assert (SCHEDULE[0]["start"], SCHEDULE[0]["end"]) == (50096, 50864)
    assert SCHEDULE[0]["run_len"] == 4
    assert all(isinstance(t, int) for t in BRANCH_RUN)
    assert (SCHEDULE[1]["start"], SCHEDULE[1]["end"]) == (50095, 50096)
    assert SCHEDULE[1]["run_len"] == 2
    assert (SCHEDULE[2]["tile"], SCHEDULE[2]["front"]) == (50863, 50864)
    assert (DEPOT, DEPOT_FRONT) == (45487, 45743)
    assert EXPECTED_ROUTE_PAIRS == len(WITNESS) - 1 == 29
    assert len(set(WITNESS)) < len(WITNESS)  # the retraced dead-end by design
    assert WITNESS[0] == PICKUP and WITNESS[-1] == EXT_STOP


# --- the corridor happy path: three built ops and the route read -------------


def test_full_phase_reaches_the_extended_route():
    """The staged extension ops admit, build and read in order through the
    production verifiers; the route read then proves the connected usable
    corridor up to the new branch stop."""
    vm = build_vm()
    attempts = run_phase(vm)
    assert [label for label, _ in attempts] == [f"op-{i:02d}" for i in range(3)]
    phase = corridor_phase_outcome(attempts)
    assert phase["verification"] == "PHASE_COMPLETE"
    assert phase["failed"] is None and phase["pending"] == []
    assert len(phase["completed"]) == 3
    for receipt in phase["completed"]:
        assert receipt["verification"] == "NATIVE_STATE_CHANGED"
        assert 0 < receipt["cost"] <= MAX_COST
        assert receipt["prelaunch_digest"] == PRELAUNCH
        assert receipt["source_save_digest"] == SOURCE
        assert receipt["error_code"] is None
    route = route_read(vm)
    assert route["connected_pairs"] == 29 and route["first_fail_index"] == -1
    assert route["cost"] == 0


def test_reply_statuses_follow_the_exchange_order():
    """Inspect replies READY, command replies BUILT and reads reply READ for
    every staged extension op."""
    vm = build_vm()
    for position, entry in enumerate(SCHEDULE):
        set_cost(vm, position)
        before = drive(vm, inspect_of(entry, position))
        assert before.status == "READY" and before.eligible is True
        assert before.cost == OP_COSTS[position]
        built = drive(vm, command_of(entry, position))
        assert built.status == "BUILT" and built.cost == OP_COSTS[position]
        assert built.funds == before.funds - OP_COSTS[position]
        readback = drive(
            vm,
            read_of(entry, position).model_copy(update={"plan": PRELAUNCH}),
        )
        assert readback.status == "READ"


def test_route_read_reports_the_observed_facts_precisely():
    """The route read is pure observation: it fixes the counted pairs, the
    head pickup facts, the new tail stop facts, the depot pin, and its cost
    stays 0."""
    vm = build_vm()
    settle = seed_funds(vm)
    run_phase(vm)
    readback = drive(vm, route_request(vm))
    assert readback.op == "route" and readback.status == "READ"
    assert readback.connected_pairs == 29 and readback.first_fail == -1
    assert readback.pickup_stop is True and readback.pickup_truck is True
    assert readback.pickup_sid == 0  # the corridor's pickup stop
    assert readback.delivery_stop is True and readback.delivery_truck is True
    assert readback.delivery_sid == 2  # the extension's own distinct station
    assert readback.pickup_sid != readback.delivery_sid
    assert readback.depot_pin_ok is True
    assert readback.cost == 0
    assert readback.funds == settle - sum(OP_COSTS.values())


def test_branch_geometry_returns_the_expected_pairs():
    """The branch full run and join report their observed pair summaries."""
    vm = build_vm()
    intent, evidence = run_group(vm, SCHEDULE[0], 0)
    assert intent.run_len == 4
    assert evidence["built"].covered == 4
    assert evidence["built"].pairs_ok == evidence["built"].pair_total == 3
    intent, evidence = run_group(vm, SCHEDULE[1], 1)
    assert intent.run_len == 2
    assert evidence["built"].covered == 2
    assert evidence["built"].pairs_ok == evidence["built"].pair_total == 1


# --- controlled native refusals (fail-closed statuses) -----------------------


def test_out_of_order_first_request_never_mutates_the_world():
    """The join op may not run before the branch run: OUT_OF_ORDER, and the
    world keeps its vacancy, balance and call counters untouched."""
    vm = build_vm()
    funds = seed_funds(vm)
    later = drive(vm, command_of(SCHEDULE[1], 1))
    assert later.status == "OUT_OF_ORDER"
    assert vm_root(vm)["real_calls"] == 0
    assert seed_funds(vm) == funds
    vm.execute("::stop_count <- ::stops.len();")
    assert vm_root(vm)["stop_count"] == 2  # only the corridor stops exist


def test_duplicate_request_id_is_dropped_without_budget_cost():
    """A reused request id is silently dropped: no reply and no budget
    charge for the duplicate."""
    vm = build_vm()
    first = inspect_of(SCHEDULE[0], 0)
    drive(vm, first)
    silently_dropped(vm, first)
    vm.execute("::sniffer.requests <- ::bridge.requests;")
    assert vm_root(vm)["sniffer"]["requests"] == 1


def test_request_budget_refuses_the_17th_unique_request():
    """10 planned + 6 slack reads fill the 16-request budget; the request
    after that is dropped without any reply (never re-labelled)."""
    vm = build_vm()
    run_phase(vm)
    route_read(vm)
    for position in range(90, 96):
        reply = drive(vm, read_of(SCHEDULE[0], position))
        assert reply.status == "READ"
    vm.execute("::sniffer.requests <- ::bridge.requests;")
    assert vm_root(vm)["sniffer"]["requests"] == REQUEST_BUDGET == 16
    with pytest.raises(AssertionError, match="dropped request"):
        drive(vm, read_of(SCHEDULE[0], 96))


def test_road_eligibility_gate_refuses_before_the_branch_run_built():
    """The join's own eligibility verdict is the D4 corner rule: both
    endpoints company road with no existing link. On the unbuilt branch the
    pair-correct states are exactly honest — 50095 is company road, 50096 is
    not — so `road` eligibility is genuinely false. The wire itself refuses
    the pre-stage request with OUT_OF_ORDER and no mutation of any kind."""
    vm = build_vm()
    funds = seed_funds(vm)
    before = drive(vm, inspect_of(SCHEDULE[1], 1))
    assert before.status == "OUT_OF_ORDER"  # the stage gate runs first
    assert before.eligible is False  # no observation reported as admissible
    assert vm_root(vm)["real_calls"] == 0 and seed_funds(vm) == funds
    vm.execute(
        "::join_obs <- ::bridge.ObserveRoad(50095, 50096, 0);"
        '::join_eligible <- ::bridge.Eligible("road", 0, ::join_obs);'
        "::join_linked <- ::bridge.Linked(50095, 50096);"
    )
    obs = vm_root(vm)["join_obs"]
    assert obs["owner0"] == 0 and obs["road0"] is True
    assert obs["owner1"] == -1 and obs["road1"] is False
    assert obs["covered"] == 1 and obs["pairs_ok"] == 0 and obs["pair_total"] == 1
    assert vm_root(vm)["join_eligible"] is False  # the eligibility gate itself
    assert vm_root(vm)["join_linked"] is False
    later = drive(vm, command_of(SCHEDULE[1], 1))
    assert later.status == "OUT_OF_ORDER"
    assert vm_root(vm)["real_calls"] == 0 and seed_funds(vm) == funds


def test_station_refuses_when_the_front_is_not_company_road():
    """A stop may only be admitted fronting an existing company road: with
    the branch front 50608 not company road (fixture: its road and
    ownership are absent), inspection refuses NOT_BUILDABLE and never
    quotes, commands or mutates."""
    vm = build_vm()
    for position in range(2):
        run_group(vm, SCHEDULE[position], position)
    funds = seed_funds(vm)
    vm.execute(
        "::tiles[50864].flags = ::tiles[50864].flags & ~(0x0080 | 0x0200);"
        "::tiles[50864].owner = -1;"
    )
    before = drive(vm, inspect_of(SCHEDULE[2], 2))
    assert before.status == "NOT_BUILDABLE"
    assert before.eligible is False
    assert before.front_owner == -1 and before.stop is False
    assert vm_root(vm)["real_calls"] == 2 and seed_funds(vm) == funds


def test_station_refuses_when_the_stop_tile_is_already_a_stop():
    """The extension stop tile carries a stop already (fixture: a pre-placed
    stop at 50863): the zero-surprise chain at stage-0 surveys the stop tiles
    itself, so the very first inspection refuses NOT_BUILDABLE — no road/op
    exchange is quoted, commanded or mutated at all."""
    vm = build_vm(pre_ext_stop=True)
    funds = seed_funds(vm)
    before = drive(vm, inspect_of(SCHEDULE[0], 0))
    assert before.status == "NOT_BUILDABLE"
    assert before.front_slope == 0 and before.stop_slope == 0  # flat, but occupied
    assert vm_root(vm)["real_calls"] == 0 and seed_funds(vm) == funds
    vm.execute("::stop_count <- ::stops.len();")
    assert vm_root(vm)["stop_count"] == 3  # the witnessed pre-existing stop
    later = drive(vm, command_of(SCHEDULE[0], 0))
    assert later.status == "STALE_ADMISSION"  # no RESET: refusal held with a new kind
    assert vm_root(vm)["real_calls"] == 0 and seed_funds(vm) == funds


def test_over_ceiling_quote_reports_cost_limit():
    vm = build_vm()
    set_cost(vm, 0)
    vm_root(vm)["quote_cost"] = 3000
    before = drive(vm, inspect_of(SCHEDULE[0], 0))
    assert before.status == "COST_LIMIT"
    assert vm_root(vm)["real_calls"] == 0


def test_insufficient_funds_refuses_inspection():
    vm = build_vm()
    set_cost(vm, 0)
    vm_root(vm)["funds"] = 10
    before = drive(vm, inspect_of(SCHEDULE[0], 0))
    assert before.status == "INSUFFICIENT_FUNDS"
    assert vm_root(vm)["real_calls"] == 0


def test_quote_cost_drift_between_admission_and_execution():
    """A re-quote that differs from the admitted cost never runs a command."""
    vm = build_vm()
    entry, position = SCHEDULE[0], 0
    set_cost(vm, position)
    before = drive(vm, inspect_of(entry, position))
    assert before.status == "READY"
    admit(entry, position, before)
    vm_root(vm)["quote_cost"] = OP_COSTS[position] + 1
    built = drive(vm, command_of(entry, position))
    assert built.status == "COST_CHANGED"
    assert vm_root(vm)["real_calls"] == 0


def test_command_without_fresh_admission_is_stale():
    vm = build_vm()
    stale = drive(vm, command_of(SCHEDULE[0], 0))
    assert stale.status == "STALE_ADMISSION"
    assert vm_root(vm)["real_calls"] == 0


def test_admitted_plan_drift_blocks_the_command():
    """A command request carrying a plan other than the latched admission
    seal must never run; the handler compares it at the mutation boundary."""
    vm = build_vm()
    set_cost(vm, 0)
    before = drive(vm, inspect_of(SCHEDULE[0], 0))
    admit(SCHEDULE[0], 0, before)
    drift = drive(vm, command_of(SCHEDULE[0], 0).model_copy(update={"plan": OTHER_PLAN}))
    assert drift.status == "STALE_ADMISSION"
    assert vm_root(vm)["real_calls"] == 0


def test_zero_cost_quote_is_a_terminal_admission_refusal():
    vm = build_vm()
    set_cost(vm, 0)
    vm_root(vm)["no_op"] = True
    before = drive(vm, inspect_of(SCHEDULE[0], 0))
    assert before.status == "REJECTED"
    assert before.eligible is True and before.cost == 0
    with pytest.raises(ValueError, match="positive tested cost"):
        admit(SCHEDULE[0], 0, before)
    assert vm_root(vm)["real_calls"] == 0


def test_quote_reject_refuses_admission_without_a_command():
    vm = build_vm(quote_reject=True)
    set_cost(vm, 0)
    before = drive(vm, inspect_of(SCHEDULE[0], 0))
    assert before.status == "REJECTED"
    assert vm_root(vm)["real_calls"] == 0


# --- the zero-surprise pre-admission gate -------------------------------------


def test_gate_refuses_a_sloped_stop_tile_before_any_mutation():
    """The exact halted D5-CORRIDOR-EXTENSION-1 failure mode, replayed: the
    stop tile 50863 carries live raised corners while the whole run-front
    road world would otherwise admit. The stage-0 gate surveys the stop tiles
    itself, so the first inspection refuses NOT_BUILDABLE with the stop's own
    native slope fact in the reply and NOTHING is quoted, built or debited."""
    vm = build_vm()
    vm.execute("::tiles[50863].c = {N=9, E=1, W=9, S=1};")  # live slope 9
    funds = seed_funds(vm)
    before = drive(vm, inspect_of(SCHEDULE[0], 0))
    assert before.status == "NOT_BUILDABLE"
    assert before.stop_slope == 9 and before.stop_min_height == 1
    assert before.front_slope == 0  # the front is live-flat, the stop is not
    assert before.cost == 0
    assert vm_root(vm)["real_calls"] == 0 and seed_funds(vm) == funds
    later = drive(vm, command_of(SCHEDULE[0], 0))
    assert later.status == "STALE_ADMISSION"
    assert vm_root(vm)["real_calls"] == 0 and seed_funds(vm) == funds


def test_gate_quotes_the_surveyed_sloped_run_tiles_before_any_mutation():
    """The surveyed terrace-ramp run tiles (live slope 12/12/8 of record in
    the D5-TERRAIN-SURVEY-1 receipts) are not admission refusals: the natural
    straight road on such escarpment ramps is native legal with a foundation
    price under live build_on_slopes, so the stage-0 gate previews the whole
    full-run command natively and admits it at its positive quote — before
    any mutation (no road piece, no debit, no stop)."""
    vm = build_vm()
    for tile, slope in ((50096, 12), (50352, 12), (50608, 8)):
        vm.execute(f"::survey_slope <- GSTile.GetSlope({tile});")
        assert vm_root(vm)["survey_slope"] == slope
    funds = seed_funds(vm)
    before = drive(vm, inspect_of(SCHEDULE[0], 0))
    assert before.status == "READY" and before.eligible is True
    assert before.cost == 20  # the positive native run quote, not a flat-rate guess
    assert before.stop_slope is None  # no stop facts block the road preview
    assert vm_root(vm)["real_calls"] == 0 and seed_funds(vm) == funds
    vm.execute("::stop_count <- ::stops.len();")
    assert vm_root(vm)["stop_count"] == 2  # only the corridor stops exist


def test_gate_refuses_road_on_a_run_tile_before_any_mutation():
    """A road or ownership already on any branch run tile refuses the gate:
    the chain never lets a road piece start while the footprint is not
    live-vacant end to end."""
    vm = build_vm()
    vm.execute(
        "::tiles[50608].flags = ::tiles[50608].flags | 0x0080 | 0x0200;::tiles[50608].owner = 0;"
    )
    funds = seed_funds(vm)
    before = drive(vm, inspect_of(SCHEDULE[0], 0))
    assert before.status == "NOT_BUILDABLE"
    assert vm_root(vm)["real_calls"] == 0 and seed_funds(vm) == funds


def test_gate_refuses_a_native_fact_on_the_stop_tile():
    """A tile whose census-existence the live world contradicts (the stop
    tile is not a valid map tile) is an UNKNOWN: the gate refuses
    UNSUPPORTED_NATIVE_FACT with zero mutation, never an assumed pass."""
    vm = build_vm()
    vm.execute("delete ::tiles[50863];")
    funds = seed_funds(vm)
    before = drive(vm, inspect_of(SCHEDULE[0], 0))
    assert before.status == "UNSUPPORTED_NATIVE_FACT"
    assert vm_root(vm)["real_calls"] == 0 and seed_funds(vm) == funds


def test_gate_refuses_a_joint_path_zero_cost_quote():
    """A native test quote of zero cost is a terminal REJECTED refusal at
    the gate itself (the join preview quote carries the zero-cost
    eligibility-free verdict)."""
    vm = build_vm()
    set_cost(vm, 0)
    vm_root(vm)["no_op"] = True
    before = drive(vm, inspect_of(SCHEDULE[0], 0))
    assert before.status == "REJECTED"
    assert vm_root(vm)["real_calls"] == 0


def test_gate_refuses_ceiling_exceeding_preview_quote():
    """The join command's native preview quote over the per-command ceiling
    refuses the whole gate (the other staged ops stay unquoted)."""
    vm = build_vm()
    set_cost(vm, 0)
    vm_root(vm)["quote_cost"] = 3000
    before = drive(vm, inspect_of(SCHEDULE[0], 0))
    assert before.status == "COST_LIMIT"
    assert vm_root(vm)["real_calls"] == 0


def test_gate_refuses_bank_below_preview_quote():
    """Live funds under the join preview quote refuse the gate."""
    vm = build_vm()
    set_cost(vm, 0)
    vm_root(vm)["funds"] = 10
    before = drive(vm, inspect_of(SCHEDULE[0], 0))
    assert before.status == "INSUFFICIENT_FUNDS"
    assert vm_root(vm)["real_calls"] == 0


def test_gate_refuses_join_preview_quote_refusal():
    """A native quote refusal at the gate's preview is a terminal REJECTED
    refusal with nothing built."""
    vm = build_vm(quote_reject=True)
    funds = seed_funds(vm)
    before = drive(vm, inspect_of(SCHEDULE[0], 0))
    assert before.status == "REJECTED"
    assert vm_root(vm)["real_calls"] == 0 and seed_funds(vm) == funds


def test_prelaunch_package_has_no_forbidden_op_surface():
    """The shipped package's own text contains no vehicle, order, cargo,
    terraforming, demolition, rail, dock, airport or depot-build op surface:
    only the three staged road/stop commands may ever exist in the plan."""
    text = (PACKAGE / "main.nut").read_text()
    for forbidden in (
        "BuyVehicle",
        "SetOrder",
        "AppendOrder",
        "VehicleIsValid",
        "DemolishTile",
        "BuildRoadDepotUnchecked",
        "LevelGround",
        "PlantTree",
        "ExecuteTerraform",
        "BuildRail",
        "BuildDock",
        "BuildAirport",
        "CargoAtDist",
        "CreatePayment",
    ):
        assert forbidden not in text
    # The build surface is exactly the three staged commands.
    assert "GSRoad.BuildRoadFull(" in text
    assert "GSRoad.BuildRoad(" in text
    assert "GSRoad.BuildRoadStation(" in text


# --- route read witnesses -----------------------------------------------------


def test_route_witness_with_a_non_stop_tail_reports_no_delivery_stop():
    """A witness whose tail is a plain road tile (not a stop) classifies
    delivery_stop false and so stays ineligible: pure observation, no
    mutation, no cost."""
    vm = build_vm()
    run_phase(vm)
    request = route_request(vm, request_id="route-tail", tiles=WITNESS[:-1])
    readback = drive(vm, request)
    assert readback.status == "READ"
    assert readback.delivery_stop is False
    assert readback.delivery_truck is False and readback.delivery_sid == -1
    assert readback.connected_pairs == len(WITNESS) - 2 and readback.first_fail == -1
    assert readback.eligible is False
    assert readback.cost == 0


def test_route_witness_with_one_broken_pair_pins_the_fail_index():
    """A witness across the not-yet-built join fails exactly at the broken
    pair index and stays ineligible until the join exists."""
    vm = build_vm()
    request = route_request(vm, request_id="route-break", tiles=(50095, 50096))
    readback = drive(vm, request)
    assert readback.status == "READ"
    assert readback.connected_pairs == 0 and readback.first_fail == 0
    assert readback.eligible is False
    assert readback.cost == 0


# --- the STATION_NEW discipline -----------------------------------------------


def test_station_build_records_the_exact_new_station_arguments():
    """The build call must pass GSRoad.ROADVEHTYPE_TRUCK and
    GSStation.STATION_NEW: a new distinct station is the pinned design, and
    the stub records the invocation arguments verbatim."""
    vm = build_vm()
    run_phase(vm)
    calls = vm_root(vm)["station_calls"]
    assert len(calls) == 3  # two test-mode quotes + one real command
    for recorded in calls:
        assert recorded[0] == EXT_STOP and recorded[1] == EXT_FRONT
        assert recorded[2] == 0  # GSRoad.ROADVEHTYPE_TRUCK
        assert recorded[3] == 0xFE  # GSStation.STATION_NEW: joining is impossible
    # The stub's station registry hands out incrementing ids instead of
    # merging: a second build at an adjacent tile receives its own sid, so a
    # second STATION_NEW build can never join the extension station, and the
    # corridor stops keep their pinned sids 0 and 1.
    vm.execute("::second_sid <- stub_build_road_stop(50865, 50864);")
    second = vm_root(vm)["second_sid"]
    assert second == 3 and second != 2
    vm.execute(
        "::ext_sid <- GSStation.GetStationID(50863);::join_sid <- GSStation.GetStationID(50865);"
    )
    assert vm_root(vm)["ext_sid"] == 2 and vm_root(vm)["join_sid"] == 3
    vm.execute(
        "::pickup_sid <- GSStation.GetStationID(45748);"
        "::delivery_sid <- GSStation.GetStationID(50351);"
    )
    assert vm_root(vm)["pickup_sid"] == 0
    assert vm_root(vm)["delivery_sid"] == 1


def test_extension_station_exchange_group_verifies():
    """The station op's full exchange group verifies through the production
    verifier like any other staged op."""
    vm = build_vm()
    for position in range(2):
        run_group(vm, SCHEDULE[position], position)
    intent, evidence = run_group(vm, SCHEDULE[2], 2)
    built = evidence["built"]
    assert built.status == "BUILT"
    assert built.stop is True and built.truck is True
    assert built.drive_through is False and built.depot is False
    assert built.sid == 2 and built.cost == OP_COSTS[2]
    assert built.stop_owner == 0 and built.front_owner == 0
    assert built.linked is True and built.front == EXT_FRONT
    receipt = verify_corridor(intent, evidence["before"], built, evidence["independent"])
    assert receipt["kind"] == "station" and receipt["operation"] == "ROAD_STATION"
    assert json.dumps(receipt["pins"]) == json.dumps(
        dict(start=None, end=None, tile=EXT_STOP, front=EXT_FRONT, tiles=None)
    )
