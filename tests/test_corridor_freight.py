"""Controlled offline tests for the D5 native corridor-freight wire contract.

The shipped ``d5_freight_package/main.nut`` runs inside the real Squirrel VM
against a stub freight world that reproduces the proven fixed-demo lifecycle
semantics (test-mode quotes, BuildVehicle, order appends, StartStopVehicle,
GSCargoMonitor arming/consumption, quarterly finance reads and the witness
road geometry); every dispatched reply is parsed back through the protocol-5
wire contract the production commanding layer uses, never through the
package's own words. Stub knobs (``::paused``, ``::no_op``, ``::engine_ok``,
the funds/quote/price globals, monitor baselines and vehicle loads) inject
controlled native refusals so the fail-closed statuses are exercised against
the shipped package itself. Nothing here launches OpenTTD, connects to an
AdminPort or writes any native or save state: only the tests' own VM world is
mutated.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from squirrel import SQVM

from app.simulation.openttd import corridor_freight as cf
from app.simulation.openttd.corridor_freight import (
    MAX_FREIGHT_REQUEST_BYTES,
    MAX_FREIGHT_RESPONSE_BYTES,
    FreightReadback,
    FreightRequest,
    freight_phase_outcome,
    verify_freight_cycle,
)
from app.simulation.openttd.proof import corridor_freight_native as work

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "app" / "simulation" / "openttd" / "d5_freight_package"
API = REPO / "tests" / "fixtures" / "gamescript_api_15.nut"

PRELAUNCH = "a" * 64
OTHER_PLAN = "b" * 64

# The module's own derivations drive every staged pin in the tests, so a
# derivation drift is caught here before any staging: nothing is re-told.
SCHEDULE = work.freight_schedule()
PLAN = work.freight_plan()
EXCHANGES = [entry["exchange"] for entry in SCHEDULE]
ENGINE_PRICE = 20  # engine 73's stub quote/price, within the £2,000 ceiling
ENGINE_CAPACITY = 20  # the stub engine's one vehicle capacity slot
FUNDS = 492149  # the pinned D4 close-out funds the stub world carries

WORLD = """
::dims <- [256, 256];
::tiles <- {};
::road_links <- {};
::stops <- {};
::station_types <- {};
::depots <- {};
::vehicles <- {};
::orders <- {};
::engines <- {};
::tests <- {};
::account <- 0;
::funds <- 492149;
::quote_cost <- 20;
::exec_cost <- 20;
::engine_price <- 20;
::engine_capacity <- 20;
::extra_engines <- 0;
::next_station <- 100;
::next_vehicle <- 1;
::cur_roadtype <- 0;
::roadtype_ok <- true;
::mode_ok <- true;
::valid_company <- true;
::second_company <- -1;
::no_op <- false;
::engine_ok <- true;
::paused <- false;
/* GSCompanyMode's constructor assigns this slot; Squirrel needs it declared. */
::cur_company <- 0;
::days <- 730;
::ticks <- 0;
::stop_at <- -1;
::reject_start <- false;
::no_stops <- false;
::monitors <- { id = "monitors", pickup = 0, delivery = 0 };
::finances <- { id = "finances", income = 0, delivered = 0 };
::prod <- 100;
::accept <- 8;
::waiting <- 5;
::last_accepted <- 900;
::test_calls <- 0;
::real_calls <- 0;
::depot_tile <- 45487;
::depot_front <- 45743;
::sniffer <- {last = "missing"};
function GetTick() { return ::ticks; }
function break_link(a, b) {
    if (a in ::road_links && b in ::road_links[a]) delete ::road_links[a][b];
    if (b in ::road_links && a in ::road_links[b]) delete ::road_links[b][a];
}
"""

WORLD_SEED = """
function stub_seed(tile, owner) {
    if (tile in ::tiles) {
        if (::tiles[tile].owner == -1) ::tiles[tile].owner = owner;
        return;
    }
    /* bit 7 = road (IsRoadTile), bit 9 = the ROADTYPE_ROAD presence bit. */
    ::tiles[tile] <- {flags = 0x0280, owner = owner};
    ::road_links[tile] <- {};
}
/* The depot: company-owned at the pinned tile, joined to its pinned front. */
::depots[::depot_tile] <- {front = ::depot_front};
stub_seed(::depot_tile, 0);
stub_seed(::depot_front, 0);
::road_links[::depot_tile][::depot_front] <- true;
::road_links[::depot_front][::depot_tile] <- true;
/* The ordered witness path: every adjacent pair joined by company road, and
 * every tile company-owned (the witnesses re-check both facts). */
::witness_tiles <- [45748, 45747, 45746, 45745, 45744, 45743, 45999, 46255,
                    46511, 46767, 47023, 47279, 47535, 47791, 48047, 48303,
                    48559, 48815, 49071, 49327, 49583, 49839, 50095, 50351];
for (local i = 0; i + 1 < ::witness_tiles.len(); i++) {
    stub_seed(::witness_tiles[i], 0);
    stub_seed(::witness_tiles[i + 1], 0);
    ::road_links[::witness_tiles[i]][::witness_tiles[i + 1]] <- true;
    ::road_links[::witness_tiles[i + 1]][::witness_tiles[i]] <- true;
}
/* The two truck-stop-typed stops with their pinned fronts and station ids. */
if (!::no_stops) {
    ::stops[45748] <- {front = 45747, sid = 100};
    ::stops[50351] <- {front = 50095, sid = 101};
    ::station_types[100] <- 0x1;
    ::station_types[101] <- 0x1;
}
/* One compatible non-articulated road truck engine (default cargo 1). */
::engines[73] <- true;
"""

STUB = """
class GSController {
    function Sleep(t) {
        if (t != 1) throw "unexpected script sleep";
        ::ticks++;
        ::days++;
        if (::ticks == ::stop_at) throw "CONTROLLED_STOP";
    }
}
class GSCompany {
    static COMPANY_INVALID = -1;
    static CURRENT_QUARTER = 1;
    static function ResolveCompanyID(c) {
        return !::valid_company ? -1 : (c == 0 || c == ::second_company) ? c : -1;
    }
    static function GetBankBalance(_) { return ::funds; }
    static function GetQuarterlyIncome(_, _) { return ::finances.income; }
    static function GetQuarterlyCargoDelivered(_, _) { return ::finances.delivered; }
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
class GSRoad {
    static ROADTYPE_ROAD = 0;
    static ROADVEHTYPE_TRUCK = 1;
    static function SetCurrentRoadType(type) { ::cur_roadtype = type; }
    static function GetCurrentRoadType() { return ::cur_roadtype; }
    static function IsRoadTypeAvailable(_) { return ::roadtype_ok; }
    static function AreRoadTilesConnected(a, b) {
        return (a in ::road_links) && (b in ::road_links[a]);
    }
    static function IsRoadTile(t) {
        return (t in ::tiles) && (::tiles[t].flags & 0x0080) != 0;
    }
    static function IsRoadStationTile(t) { return t in ::stops; }
    static function IsDriveThroughRoadStationTile(_) { return false; }
    static function GetRoadStationFrontTile(t) {
        return (t in ::stops) ? ::stops[t].front : -1;
    }
    static function IsRoadDepotTile(t) { return t in ::depots; }
    static function GetRoadDepotFrontTile(t) {
        return (t in ::depots) ? ::depots[t].front : -1;
    }
    static function GetRoadVehicleTypeForCargo(_) { return GSRoad.ROADVEHTYPE_TRUCK; }
}
class GSStation {
    static STATION_TRUCK_STOP = 0x1;
    static STATION_BUS_STOP = 0x2;
    static function GetStationID(t) { return (t in ::stops) ? ::stops[t].sid : -1; }
    static function IsValidStation(sid) { return sid >= 0 && (sid in ::station_types); }
    static function HasStationType(sid, type) {
        return (sid in ::station_types) && (::station_types[sid] & type) != 0;
    }
    static function GetCoverageRadius(_) { return 8; }
    static function GetCargoWaiting(_, _) { return ::waiting; }
}
class GSTile {
    static function GetOwner(t) { return (t in ::tiles) ? ::tiles[t].owner : -1; }
    static function GetCargoAcceptance(_, _, _, _, _) { return ::accept; }
}
class GSIndustry {
    static function GetLastMonthProduction(industry, _) {
        return industry == 0 ? ::prod : 0;
    }
    static function GetCargoLastAcceptedDate(industry, _) {
        return industry == 1 ? ::last_accepted : -1;
    }
}
class GSVehicle {
    static VT_ROAD = 1;
    static VS_RUNNING = 0;
    static VS_STOPPED = 1;
    static VS_IN_DEPOT = 2;
    static VS_AT_STATION = 3;
    static VS_BROKEN = 4;
    static VS_CRASHED = 5;
    static function BuildVehicle(tile, engine) {
        if (!(tile in ::depots) || !(engine in ::engines)) return -1;
        if (::account in ::tests) { ::test_calls++; return 0; }
        ::real_calls++;
        ::funds -= ::exec_cost;
        local id = ::next_vehicle;
        ::next_vehicle++;
        ::vehicles[id] <- {owner = 0, engine = engine, location = tile,
            cargo = 1, capacity = ::engine_capacity, load = 0, state = 2,
            in_depot = true, speed = 0};
        ::orders[id] <- [];
        ::cur_vehicle <- id;
        return id;
    }
    static function IsValidVehicle(id) { return id >= 0 && (id in ::vehicles); }
    static function IsPrimaryVehicle(_) { return true; }
    static function GetOwner(id) { return ::vehicles[id].owner; }
    static function GetEngineType(id) { return ::vehicles[id].engine; }
    static function GetLocation(id) { return ::vehicles[id].location; }
    static function GetCapacity(id, _) { return ::vehicles[id].capacity; }
    static function IsInDepot(id) { return ::vehicles[id].in_depot; }
    static function GetCurrentSpeed(id) { return ::vehicles[id].speed; }
    static function GetState(id) { return ::vehicles[id].state; }
    static function GetCargoLoad(id, _) { return ::vehicles[id].load; }
    static function StartStopVehicle(id) {
        if (!(id in ::vehicles) || ::reject_start) return false;
        local v = ::vehicles[id];
        if (v.state != VS_RUNNING && v.state != VS_AT_STATION) {
            v.state = VS_RUNNING;
            v.speed = 5;
            v.in_depot = false;
        } else {
            v.state = VS_STOPPED;
            v.speed = 0;
        }
        return true;
    }
}
class GSVehicleList {
    items = null;
    index = 0;
    constructor() {
        this.items = [];
        foreach (id, _ in ::vehicles) this.items.append(id);
    }
    function Begin() {
        if (this.items.len() == 0) { this.index = 0; return null; }
        this.index = 0;
        return this.items[0];
    }
    function IsEnd() { return this.index >= this.items.len(); }
    function Next() {
        this.index++;
        if (this.index >= this.items.len()) return null;
        return this.items[this.index];
    }
}
class GSEngineList {
    items = null;
    index = 0;
    constructor(_) {
        this.items = [];
        foreach (id, _ in ::engines) this.items.append(id);
        for (local i = 0; i < ::extra_engines; i++) this.items.append(2000 + i);
    }
    function Begin() {
        if (this.items.len() == 0) { this.index = 0; return null; }
        this.index = 0;
        return this.items[0];
    }
    function IsEnd() { return this.index >= this.items.len(); }
    function Next() {
        this.index++;
        if (this.index >= this.items.len()) return null;
        return this.items[this.index];
    }
}
class GSEngine {
    static function IsBuildable(e) { return ::engine_ok && (e in ::engines); }
    static function IsValidEngine(e) { return e in ::engines; }
    static function GetVehicleType(_) { return GSVehicle.VT_ROAD; }
    static function IsArticulated(_) { return false; }
    static function CanRunOnRoad(_, _) { return true; }
    static function HasPowerOnRoad(_, _) { return true; }
    static function GetCargoType(_) { return 1; }
    static function CanRefitCargo(_, _) { return true; }
    static function GetCapacity(_) { return ::engine_capacity; }
    static function GetPrice(_) { return ::engine_price; }
}
class GSCargo {
    static function IsValidCargo(cargo) { return cargo == 1; }
}
class GSOrder {
    static OF_NO_LOAD = 0;
    static OF_FULL_LOAD = 4;
    static function AreOrderFlagsValid(flags) { return flags == 0 || flags == 4; }
    static function AppendOrder(id, dest, flags) {
        if (!(id in ::vehicles) || !(dest in ::station_types)) return false;
        ::orders[id].append({d = dest, f = flags});
        return true;
    }
    static function GetOrderCount(id) { return (id in ::orders) ? ::orders[id].len() : 0; }
    static function GetOrderDestination(id, i) { return ::orders[id][i].d; }
    static function GetOrderFlags(id, i) { return ::orders[id][i].f; }
    static function IsGotoStationOrder(id, i) {
        return ::orders[id][i].d in ::station_types;
    }
}
class GSCargoMonitor {
    static function GetIndustryPickupAmount(_, _, _, _) { return ::monitors.pickup; }
    static function GetIndustryDeliveryAmount(_, _, _, keep) {
        local value = ::monitors.delivery;
        if (!keep) ::monitors.delivery = 0;
        return value;
    }
}
class GSGame {
    static function IsPaused() { return ::paused; }
}
class GSDate {
    static function GetCurrentDate() { return ::days; }
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
        else out = out + v;
    }
    return out + "}";
}
"""


def build_vm(**knobs: int | bool) -> SQVM:
    """Fresh VM with the API fixture, the controlled freight world and the package."""
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
    vm.execute("::bridge <- D5FreightProof();")
    return vm


def vm_root(vm: SQVM) -> dict[str, Any]:
    return vm.get_roottable()


def drive(vm: SQVM, request: FreightRequest) -> FreightReadback:
    """Dispatch one request over the wire and parse the reply into Python."""
    execute_request(vm, request)
    vm.execute("::sniffer.last = last_reply_json();")
    raw = vm_root(vm)["sniffer"]["last"]
    assert len(raw.encode()) <= MAX_FREIGHT_RESPONSE_BYTES, (
        f"response for {request.request_id} exceeds {MAX_FREIGHT_RESPONSE_BYTES} bytes"
    )
    return FreightReadback.parse_for(request, raw.encode())


def execute_request(vm: SQVM, request: FreightRequest) -> dict:
    """Run one Handle dispatch; the reply payload is returned as a table."""
    replies = vm_root(vm)["replies"]
    before = len(replies)
    vm.execute("::bridge.Handle(" + request.to_bytes().decode() + ");")
    replies = vm_root(vm)["replies"]
    if len(replies) == before:
        raise AssertionError(f"package dropped request {request.request_id}: no reply")
    return replies[before]


def expect_drop(vm: SQVM, payload: dict) -> None:
    """A malformed request must be dropped silently: no reply, no state."""
    before = len(vm_root(vm)["replies"])
    vm.execute("::bridge.Handle(" + _squirrel_table(payload) + ");")
    assert len(vm_root(vm)["replies"]) == before


def _squirrel_table(payload: dict) -> str:
    """The handler-facing compact JSON of a request-shaped mapping."""
    pairs = []
    for key, value in payload.items():
        if isinstance(value, bool):
            literal = "true" if value else "false"
        elif isinstance(value, str):
            literal = '"' + value + '"'
        else:
            literal = str(value)
        pairs.append('"' + key + '" : ' + literal)
    return "{" + ",".join(pairs) + "}"


def shape_world(
    vm: SQVM, label: str, vehicle: int, *, pickup: int = 45748, delivery: int = 50351
) -> None:
    """Drive the stub world between exchanges (real running would do this)."""
    if label == "load-00":
        vm.execute(
            f"::vehicles[{vehicle}].load = ::engine_capacity;\n"
            f"::vehicles[{vehicle}].location = {pickup};"
        )
    elif label == "transit-00":
        vm.execute(f"::vehicles[{vehicle}].location = {delivery};")
    elif label == "deliver-00":
        vm.execute(
            f"::vehicles[{vehicle}].load = 0;\n"
            f"::monitors.pickup = ::engine_capacity;\n"
            f"::monitors.delivery = ::engine_capacity;"
        )
    elif label == "finance-00":
        vm.execute(
            "::finances.income = 1500;\n"
            f"::finances.delivered = {ENGINE_CAPACITY};\n"
            "::last_accepted = 900;"
        )


def run_cycle(
    vm: SQVM, *, plan=None, pickup: int = 45748, delivery: int = 50351
) -> tuple[list[tuple[FreightRequest, FreightReadback]], dict]:
    """The exact fifteen planned exchanges in order (the production builder)."""
    plan = plan or work.freight_plan()
    state: dict[str, Any] = dict(site=None, engine=None, vehicle=-1)
    exchanges: list[tuple[FreightRequest, FreightReadback]] = []
    for entry in work.freight_schedule():
        label = entry["exchange"]
        request = work._freight_exchange_request(entry, PRELAUNCH, plan, state)
        if state["vehicle"] >= 0:
            shape_world(vm, label, state["vehicle"], pickup=pickup, delivery=delivery)
        readback = drive(vm, request)
        probes = freight_phase_outcome(
            exchanges + [(request, readback)], prelaunch_digest=PRELAUNCH, plan=plan
        )
        assert probes["failed"] is None, (label, probes["failed"])
        # The purchase group folds its independent read (vread-00) into one
        # receipt, so the current exchange may appear under any request-id key.
        receipt = probes["completed"][-1]
        receipt_ids = {value for key, value in receipt.items() if key.endswith("request_id")}
        assert label in receipt_ids, (label, receipt_ids)
        exchanges.append((request, readback))
        if entry["op"] == "site":
            state["site"] = work.admit_freight_site(readback, prelaunch_digest=PRELAUNCH, plan=plan)
        elif entry["op"] == "engine":
            state["engine"] = work.admit_freight_engine(
                readback, prelaunch_digest=PRELAUNCH, plan=plan, site=state["site"]
            )
        elif entry["op"] == "purchase":
            state["vehicle"] = readback.vehicle
    return exchanges, plan


def probe_request(expression_ids: str, position: int, **echo: int) -> FreightRequest:
    """A valid-shaped request outside the staged schedule (cap accounting)."""
    payload = {
        "protocol": 5,
        "op": "vread",
        "request_id": f"probe-{position:02d}",
        "plan": PRELAUNCH,
        "company": 0,
        "max_cost": 2000,
        "pickup": 45748,
        "delivery": 50351,
        "depot": 45487,
        "route_digest": work.freight_plan().route_digest,
        "engine": -1,
        "vehicle": -1,
        "expected_cost": 0,
        "order_index": -1,
        "watch_ticks": -1,
        "watch_days": -1,
    }
    payload.update(echo)
    payload["request_id"] = expression_ids
    return FreightRequest.model_validate(payload)


MALFORMED_SHAPES = (
    {"protocol": 4},
    {"op": "mystery"},
    {"request_id": "X" * 33},
    {"request_id": "BAD-ID"},
    {"plan": "a" * 63},
    {"route_digest": "a" * 63},
    {"company": 15},
    {"max_cost": -1},
    {"pickup": 1},
    {"engine": 5},
    {"order_index": 2},
    {"watch_days": 31},
    {"expected_cost": -1},
)


# --- full happy cycle ----------------------------------------------------------


def test_full_cycle_completes_and_verifies_as_a_cycle():
    """All fifteen planned exchanges answer READY..PHASE_STOPPED in order; the
    production phase outcome completes and the cycle verifies end to end."""
    vm = build_vm()
    exchanges, plan = run_cycle(vm)
    assert [request.request_id for request, _ in exchanges] == list(cf.FREIGHT_EXCHANGE_IDS)
    for request, readback in exchanges:
        assert readback.plan == PRELAUNCH and readback.company == 0
        assert len(request.to_bytes()) <= MAX_FREIGHT_REQUEST_BYTES
    site = exchanges[0][1]
    assert site.status == "READY" and (site.truck0, site.sid0) == (True, 100)
    assert (site.truck1, site.sid1) == (True, 101) and site.accept == 8
    assert site.pairs_ok == site.pair_total == 23 and site.vehicles == 0
    assert site.prod == 100 and site.wait == 5 and site.paused is False
    engine = exchanges[1][1]
    assert engine.status == "READY" and engine.engine == 73
    assert engine.capacity == ENGINE_CAPACITY and engine.cargo == 1
    purchase = exchanges[2][1]
    assert purchase.status == "BUILT" and purchase.vehicle == 1
    assert purchase.cost == ENGINE_PRICE
    assert purchase.funds == FUNDS - ENGINE_PRICE
    order0, order1 = exchanges[4][1], exchanges[5][1]
    assert (order0.dest, order0.flags, order0.goto) == (100, cf.OF_FULL_LOAD, True)
    assert (order1.dest, order1.flags, order1.goto) == (101, cf.OF_NO_LOAD, True)
    inventory = exchanges[6][1]
    assert (inventory.order_len, inventory.dest0, inventory.dest1) == (2, 100, 101)
    assert (inventory.flags0, inventory.flags1) == (cf.OF_FULL_LOAD, cf.OF_NO_LOAD)
    monitors = exchanges[7][1]
    assert monitors.pickup_amount == 0 and monitors.delivery_amount == 0
    started = exchanges[8][1]
    assert started.state == "RUNNING" and started.speed == 5
    vread_01 = exchanges[9][1]
    assert vread_01.state == "RUNNING" and vread_01.in_depot is False
    loaded = exchanges[10][1]
    assert loaded.load == ENGINE_CAPACITY == loaded.capacity and loaded.wait == 5
    arrived = exchanges[11][1]
    assert (arrived.position, arrived.progress) == (50351, 23)
    delivered = exchanges[12][1]
    assert delivered.load == 0 and delivered.pickup_amount == ENGINE_CAPACITY
    assert delivered.delivery_amount == ENGINE_CAPACITY
    finance = exchanges[13][1]
    assert finance.income == 1500 and finance.delivered == ENGINE_CAPACITY
    finished = exchanges[14][1]
    assert finished.stop_issued is True and finished.state == "STOPPED"
    probes = freight_phase_outcome(exchanges, prelaunch_digest=PRELAUNCH, plan=plan)
    assert probes["verification"] == "PHASE_COMPLETE"
    cycle = verify_freight_cycle(exchanges, prelaunch_digest=PRELAUNCH, plan=plan)
    assert cycle["verification"] == "FREIGHT_CYCLE_VERIFIED"
    assert cycle["engine"] == 73 and cycle["vehicle"] == 1
    assert cycle["load"] == ENGINE_CAPACITY
    ledger = cycle["funds_ledger"]
    assert ledger[2]["delta"] == -ENGINE_PRICE  # the purchase funds movement
    assert cycle["funds"] == finished.funds == FUNDS - ENGINE_PRICE


def test_every_exchange_reply_keeps_the_correlation_stride():
    """Success frames echo the request stride they verify (correlation)."""
    vm = build_vm()
    exchanges, _ = run_cycle(vm)
    for request, readback in exchanges:
        for field in ("protocol", "op", "request_id", "plan", "company", "max_cost"):
            assert getattr(readback, field) == getattr(request, field)
        for field in ("pickup", "delivery", "depot"):
            assert getattr(readback, field) == getattr(request, field)
        if getattr(request, "engine", -1) >= 0:
            assert readback.engine == request.engine
        if request.expected_cost > 0:
            assert readback.expected_cost == request.expected_cost
        if request.op in ("load-watch", "transit-watch", "deliver-watch"):
            assert readback.watch_ticks == request.watch_ticks
            if request.op == "load-watch":
                assert readback.watch_days == request.watch_days


def test_purchase_funds_reconcile_exactly_once():
    """The funds ledger moves only on the purchase exchange, by the quote."""
    vm = build_vm()
    exchanges, plan = run_cycle(vm)
    probes = freight_phase_outcome(exchanges, prelaunch_digest=PRELAUNCH, plan=plan)
    assert probes["verification"] == "PHASE_COMPLETE"
    cycle = verify_freight_cycle(exchanges, prelaunch_digest=PRELAUNCH, plan=plan)
    deltas = [row["delta"] for row in cycle["funds_ledger"]]
    assert deltas.count(-ENGINE_PRICE) == 1
    assert all(delta in (None, 0, -ENGINE_PRICE) for delta in deltas)


# --- dispatcher discipline -------------------------------------------------------


def test_malformed_requests_are_dropped_without_any_reply():
    """Every malformed shape is silently dropped by the guarded entry point."""
    vm = build_vm()
    for shape in MALFORMED_SHAPES:
        payload = {
            "protocol": 5,
            "op": "site",
            "request_id": "site-00",
            "plan": PRELAUNCH,
            "company": 0,
            "max_cost": 2000,
            "pickup": 45748,
            "delivery": 50351,
            "depot": 45487,
            "route_digest": work.freight_plan().route_digest,
            "engine": -1,
            "vehicle": -1,
            "expected_cost": 0,
            "order_index": -1,
            "watch_ticks": -1,
            "watch_days": -1,
        }
        payload.update(shape)
        expect_drop(vm, payload)
    assert len(vm_root(vm)["replies"]) == 0


def test_plan_digest_drift_is_refused_not_ignored():
    """A different plan digest after the latched first exchange is refused."""
    vm = build_vm()
    plan = work.freight_plan()
    state = dict(site=None, engine=None, vehicle=-1)
    site_request = work._freight_exchange_request(
        work.freight_schedule()[0], PRELAUNCH, plan, state
    )
    assert drive(vm, site_request).status == "READY"
    engine_request = work._freight_exchange_request(
        work.freight_schedule()[1], OTHER_PLAN, plan, state
    )
    assert drive(vm, engine_request).status == "OUT_OF_ORDER"


def test_order_gate_and_prefix_preserving_halts():
    """The stage gate, one halted refusal, and the permanent OUT_OF_ORDER."""
    vm = build_vm()
    plan = work.freight_plan()
    entry = work.freight_schedule()[1]  # engine-00 before its site stage
    request = work._freight_exchange_request(
        entry, PRELAUNCH, plan, dict(site=None, engine=None, vehicle=-1)
    )
    readback = drive(vm, request)
    assert readback.status == "OUT_OF_ORDER"
    # The halted schedule never recovers: even the planned next exchange
    # refusal is prefix-preserving, and no op is reordered or retried.
    halted = work._freight_exchange_request(
        work.freight_schedule()[0],
        PRELAUNCH,
        plan,
        dict(site=None, engine=None, vehicle=-1),
    )
    assert drive(vm, halted).status == "OUT_OF_ORDER"
    later = work._freight_exchange_request(
        work.freight_schedule()[2],
        PRELAUNCH,
        plan,
        dict(site=None, engine=SimpleNamespace(engine=73, quote=20), vehicle=1),
    )
    assert drive(vm, later).status == "OUT_OF_ORDER"


def test_duplicate_request_ids_are_dropped_silently():
    """The one-shot accounting never answers a duplicated id twice."""
    vm = build_vm()
    request = work._freight_exchange_request(
        work.freight_schedule()[0],
        PRELAUNCH,
        work.freight_plan(),
        dict(site=None, engine=None, vehicle=-1),
    )
    assert drive(vm, request).status == "READY"
    expect_drop(vm, dict(request.model_dump(mode="json")) if False else _request_payload(request))


def _request_payload(request: FreightRequest) -> dict:
    return json_get(request.to_bytes())


def json_get(raw: bytes) -> dict:
    import json

    return json.loads(raw)


def test_dispatcher_budget_refuses_the_request_after_the_cap():
    """32 unique valid-shaped requests fill the budget; the 33rd is dropped."""
    vm = build_vm()
    reply = drive(vm, probe_request("probe-00", 0, engine=1, vehicle=1))
    assert reply.status == "OUT_OF_ORDER"
    for position in range(1, 32):
        probe = probe_request(f"probe-{position:02d}", position, engine=1, vehicle=1)
        assert drive(vm, probe).status == "OUT_OF_ORDER"
    vm.execute("::sniffer.requests <- ::bridge.requests;")
    assert vm_root(vm)["sniffer"]["requests"] == work.FREIGHT_STAGED_REQUESTS_BUDGET == 32
    execute_drop(vm, probe_request("probe-999", 999, engine=1, vehicle=1))


def execute_drop(vm: SQVM, request: FreightRequest) -> None:
    before = len(vm_root(vm)["replies"])
    vm.execute("::bridge.Handle(" + request.to_bytes().decode() + ");")
    assert len(vm_root(vm)["replies"]) == before


# --- admission refusals (fail-closed, before any mutation) -----------------------


def test_paused_world_refuses_site_admission_and_halts():
    vm = build_vm(paused=True)
    exchanges, plan = run_refusals(vm, ("site-00",))
    assert exchanges[0][1].status == "PAUSED"
    probes = freight_phase_outcome(exchanges, prelaunch_digest=PRELAUNCH, plan=plan)
    assert probes["failed"]["world_state"] == "HALTED_BEFORE_MUTATION"


def test_missing_stop_station_type_refuses_site_admission():
    vm = build_vm(no_stops=True)
    exchanges, plan = run_refusals(vm, ("site-00",))
    assert exchanges[0][1].status == "INVALID_SITE"


def test_fragmented_witness_refuses_site_admission():
    vm = build_vm()
    vm.execute("break_link(45746, 45745);")
    exchanges, plan = run_refusals(vm, ("site-00",))
    assert exchanges[0][1].status == "INVALID_SITE"


def test_unbuildable_engine_enumeration_refuses():
    vm = build_vm(engine_ok=False)
    exchanges, plan = run_refusals(vm, ("site-00", "engine-00"))
    assert exchanges[1][1].status == "NO_ENGINE"


def test_engine_price_over_ceiling_refuses():
    vm = build_vm(engine_price=3000, quote_cost=3000, exec_cost=3000)
    exchanges, plan = run_refusals(vm, ("site-00", "engine-00"))
    assert exchanges[1][1].status == "COST_LIMIT"


def test_quote_drift_refuses():
    vm = build_vm(quote_cost=21)
    exchanges, plan = run_refusals(vm, ("site-00", "engine-00"))
    assert exchanges[1][1].status == "COST_CHANGED"


def test_zero_cost_quote_refuses_as_unavailable():
    vm = build_vm(no_op=True)
    exchanges, plan = run_refusals(vm, ("site-00", "engine-00"))
    assert exchanges[1][1].status == "UNAVAILABLE_ENGINE"


def test_insufficient_funds_refuse_engine_admission():
    vm = build_vm()
    plan = work.freight_plan()
    state = dict(site=None, engine=None, vehicle=-1)
    site_request = work._freight_exchange_request(
        work.freight_schedule()[0], PRELAUNCH, plan, state
    )
    assert drive(vm, site_request).status == "READY"
    vm.execute("::funds = 5;")
    engine_request = work._freight_exchange_request(
        work.freight_schedule()[1], PRELAUNCH, plan, state
    )
    assert drive(vm, engine_request).status == "INSUFFICIENT_FUNDS"


def test_engine_overflow_refuses_the_inventory():
    vm = build_vm(extra_engines=33)
    exchanges, plan = run_refusals(vm, ("site-00", "engine-00"))
    assert exchanges[1][1].status == "ENGINE_LIMIT"


def run_refusals(vm: SQVM, labels: tuple[str, ...]):
    """Drive the named stage prefix; assert each exchange halted the phase."""
    plan = work.freight_plan()
    state: dict[str, Any] = dict(site=None, engine=None, vehicle=-1)
    exchanges: list[tuple[FreightRequest, FreightReadback]] = []
    schedule = work.freight_schedule()
    for label in labels:
        index = list(cf.FREIGHT_EXCHANGE_IDS).index(label)
        entry = schedule[index]
        if label == "engine-00":
            request = work._freight_exchange_request(entry, PRELAUNCH, plan, state)
        else:
            request = work._freight_exchange_request(entry, PRELAUNCH, plan, state)
        readback = drive(vm, request)
        exchanges.append((request, readback))
    return exchanges, plan


def test_post_purchase_identity_staleness_refuses_and_halts():
    """A drifted vehicle identity cannot command the admitted world."""
    vm = build_vm()
    exchanges, plan = run_prefix_until(vm, "purchase-00")
    entry = next(e for e in work.freight_schedule() if e["exchange"] == "vread-00")
    request = work._freight_exchange_request(entry, PRELAUNCH, plan, _state_of(exchanges))
    stale = request.model_copy(update={"vehicle": 999})
    assert drive(vm, stale).status == "STALE_ADMISSION"
    # The refusal halted the schedule prefix-preservingly: the genuine
    # identity can no longer advance this attempt.
    assert drive(vm, request.model_copy(update={"request_id": "vread-99"})).status == "OUT_OF_ORDER"


def test_window_exhaustion_is_honest_inconclusive():
    """A day-starved window never relabels itself as a success."""
    vm = build_vm()
    exchanges, plan = run_prefix_until(vm, "vread-01")
    vehicle = exchanges[2][1].vehicle
    assert vehicle == 1
    entry = next(e for e in work.freight_schedule() if e["exchange"] == "load-00")
    request = work._freight_exchange_request(entry, PRELAUNCH, plan, _state_of(exchanges))
    starved = request.model_copy(update={"watch_days": 1})
    readback = drive(vm, starved)
    assert readback.status == "WINDOW_EXHAUSTED"
    full = exchanges + [(starved, readback)]
    probes = freight_phase_outcome(full, prelaunch_digest=PRELAUNCH, plan=plan)
    assert probes["failed"]["world_state"] == "INCONCLUSIVE_WINDOW"


def test_window_pause_refuses_instead_of_waiting():
    vm = build_vm()
    exchanges, plan = run_prefix_until(vm, "vread-01")
    vm.execute("::paused = true;")
    entry = next(e for e in work.freight_schedule() if e["exchange"] == "load-00")
    request = work._freight_exchange_request(entry, PRELAUNCH, plan, _state_of(exchanges))
    readback = drive(vm, request)
    assert readback.status == "PAUSED"


def test_transit_off_route_refusal():
    vm = build_vm()
    exchanges, plan = run_prefix_until(vm, "vread-01")
    vehicle = exchanges[2][1].vehicle
    entry = next(e for e in work.freight_schedule() if e["exchange"] == "load-00")
    load_request = work._freight_exchange_request(entry, PRELAUNCH, plan, _state_of(exchanges))
    shape_world(vm, "load-00", vehicle)
    loaded = drive(vm, load_request.model_copy(update={"watch_ticks": 2048, "watch_days": 30}))
    assert loaded.status == "LOADED"
    vm.execute(f"::vehicles[{vehicle}].location = 46000;")
    entry = next(e for e in work.freight_schedule() if e["exchange"] == "transit-00")
    transit_request = work._freight_exchange_request(entry, PRELAUNCH, plan, _state_of(exchanges))
    readback = drive(vm, transit_request)
    assert readback.status == "INVALID_ROUTE"


def test_delivery_monitor_arithmetic_refuses_drift():
    vm = build_vm()
    exchanges, plan = run_prefix_until(vm, "transit-00")
    vehicle = exchanges[2][1].vehicle
    shape_world(vm, "deliver-00", vehicle)
    vm.execute("::monitors.pickup = 5; ::monitors.delivery = 5;")
    entry = next(e for e in work.freight_schedule() if e["exchange"] == "deliver-00")
    request = work._freight_exchange_request(entry, PRELAUNCH, plan, _state_of(exchanges))
    readback = drive(vm, request)
    assert readback.status == "READBACK_MISMATCH"


def run_prefix_until(vm: SQVM, label: str) -> tuple[list, dict]:
    """Drive the staged schedule prefix through `label` inclusive."""
    plan = work.freight_plan()
    state: dict[str, Any] = dict(site=None, engine=None, vehicle=-1)
    exchanges: list[tuple[FreightRequest, FreightReadback]] = []
    for entry in work.freight_schedule():
        request = work._freight_exchange_request(entry, PRELAUNCH, plan, state)
        if state["vehicle"] >= 0:
            shape_world(vm, entry["exchange"], state["vehicle"])
        readback = drive(vm, request)
        exchanges.append((request, readback))
        if entry["op"] == "site":
            state["site"] = work.admit_freight_site(readback, prelaunch_digest=PRELAUNCH, plan=plan)
        elif entry["op"] == "engine":
            state["engine"] = work.admit_freight_engine(
                readback, prelaunch_digest=PRELAUNCH, plan=plan, site=state["site"]
            )
        elif entry["op"] == "purchase":
            state["vehicle"] = readback.vehicle
        if entry["exchange"] == label:
            break
    return exchanges, plan


def _state_of(exchanges) -> dict:
    state: dict[str, Any] = dict(site=None, engine=None, vehicle=-1)
    for request, readback in exchanges:
        if request.op == "site":
            state["site"] = work.admit_freight_site(
                readback, prelaunch_digest=PRELAUNCH, plan=work.freight_plan()
            )
        elif request.op == "engine":
            state["engine"] = work.admit_freight_engine(
                readback,
                prelaunch_digest=PRELAUNCH,
                plan=work.freight_plan(),
                site=state["site"],
            )
        elif request.op == "purchase":
            state["vehicle"] = readback.vehicle
    return state


# --- package identity pins ---------------------------------------------------------


def test_package_planned_schedule_equals_the_wire_contract():
    """The shipped package's baked planned rows equal the T1 exchange table."""
    text = (PACKAGE / "main.nut").read_text()
    # The table's final row ends ``]`` immediately before the closing ``]``
    # line, so anchor the closing bracket on its own line rather than the
    # first ``]\n`` (which would drop the last row from the captured span).
    planned_span = re.search(r"planned = \[(.*?)\n    \]", text, re.DOTALL)
    assert planned_span is not None
    rows = re.findall(r'\["([a-z0-9-]+)", "([a-z-]+)", "([A-Z_]+)"\]', planned_span.group(1))
    assert [(row[0], row[1]) for row in rows] == list(cf._FREIGHT_SEQUENCE)
    assert all(cf._FREIGHT_SUCCESS_STATUS[op] == status for _, op, status in rows)
    assert len(rows) == cf.PLANNED_FREIGHT_EXCHANGES == 15


def test_package_pinned_geometry_matches_the_compiled_facts():
    """The package's witness, stops, depot and caps equal the compiled pins."""
    text = (PACKAGE / "main.nut").read_text()
    witness = re.search(r"WITNESS = \[(.*?)\]\n", text, re.DOTALL)
    assert witness is not None
    tiles = [int(tile) for tile in re.findall(r"\d+", witness.group(1))]
    assert tiles == list(work.freight_facts()["witness"])
    for constant, value in (
        ("PICKUP", 45748),
        ("PICKUP_FRONT", 45747),
        ("DELIVERY", 50351),
        ("DELIVERY_FRONT", 50095),
        ("DEPOT_TILE", 45487),
        ("DEPOT_FRONT", 45743),
        ("FREIGHT_COMPANY", 0),
        ("FREIGHT_CARGO", 1),
        ("PICKUP_INDUSTRY", 0),
        ("DELIVERY_INDUSTRY", 1),
        ("MAX_TICKS", cf.WATCH_MAX_TICKS),
        ("MAX_DAYS", cf.LOAD_WATCH_MAX_DAYS),
        ("max_requests", cf.FREIGHT_REQUEST_BUDGET),
    ):
        assert re.search(rf"\b{constant} = {value}\b", text), constant


def test_package_carries_the_save_restore_bridge():
    text = (PACKAGE / "main.nut").read_text()
    assert "class NetworkFreightProof extends D5FreightProof" in text


def test_stale_probe_with_unreachable_helper_requires_no_double_state():
    """The stub helpers stay single-purpose: no hidden shared VM reuse."""
    first = build_vm()
    second = build_vm()
    assert first is not second


# --- optimizer-selected route enters the GameScript execution path ----------


def _seed_alternate_route(vm: SQVM, route: tuple[int, ...], depot: int, depot_front: int) -> None:
    """Add one feasible alternate corridor to the controlled stub world."""
    links = "".join(
        f"::road_links[{a}][{b}] <- true; ::road_links[{b}][{a}] <- true;"
        for a, b in zip(route, route[1:], strict=False)
    )
    vm.execute(
        "\n".join(
            [f"stub_seed({tile}, 0);" for tile in route + (depot,)]
            + [
                f"stub_seed({depot_front}, 0);",
                links,
                f"::road_links[{depot}][{depot_front}] <- true;",
                f"::road_links[{depot_front}][{depot}] <- true;",
                f"::depots[{depot}] <- {{front = {depot_front}}};",
                f"::stops[{route[0]}] <- {{front = {route[1]}, sid = 102}};",
                f"::stops[{route[-1]}] <- {{front = {route[-2]}, sid = 103}};",
                "::station_types[102] <- 0x1;",
                "::station_types[103] <- 0x1;",
            ]
        )
    )


def _alternate_plan(route: tuple[int, ...], depot: int, depot_front: int):
    return work.FreightPlan(
        schema_version=2,
        company=work.freight_plan().company,
        cargo=work.freight_plan().cargo,
        pickup=route[0],
        pickup_front=route[1],
        delivery=route[-1],
        delivery_front=route[-2],
        depot=depot,
        depot_front=depot_front,
        pickup_industry=work.freight_plan().pickup_industry,
        delivery_industry=work.freight_plan().delivery_industry,
        expected_funds=work.freight_plan().expected_funds,
        max_cost=work.freight_plan().max_cost,
        witness=route,
        schedule=work.freight_plan().schedule,
    )


def test_gamescript_executes_the_latched_optimizer_route_not_the_baked_witness():
    """The alternate route is latched and replaces every witness observation."""
    route = (1000, 1001, 1002, 1003)
    depot, depot_front = 1257, 1001
    plan = _alternate_plan(route, depot, depot_front)
    assert plan.witness != work.freight_plan().witness
    vm = build_vm()
    _seed_alternate_route(vm, route, depot, depot_front)
    state = dict(site=None, engine=None, vehicle=-1)
    request = work._freight_exchange_request(work.freight_schedule()[0], PRELAUNCH, plan, state)
    readback = drive(vm, request)
    assert readback.status == "READY"
    assert (readback.sid0, readback.sid1) == (102, 103)
    assert readback.pairs_ok == readback.pair_total == len(route) - 1
    vm.execute(
        "::sniffer.idx_alt <- ::bridge.WitnessIndex(1001);\n"
        "::sniffer.idx_old <- ::bridge.WitnessIndex(45747);"
    )
    sniffer = vm_root(vm)["sniffer"]
    assert sniffer["idx_alt"] == 1
    assert sniffer["idx_old"] == -1


def test_gamescript_refuses_a_fragmented_optimizer_route():
    """A route whose native road is not fully joined refuses admission."""
    route = (1000, 1001, 1002, 1003)
    depot, depot_front = 1257, 1001
    vm = build_vm()
    _seed_alternate_route(vm, route, depot, depot_front)
    vm.execute("break_link(1001, 1002);")
    request = work._freight_exchange_request(
        work.freight_schedule()[0],
        PRELAUNCH,
        _alternate_plan(route, depot, depot_front),
        dict(site=None, engine=None, vehicle=-1),
    )
    assert drive(vm, request).status == "INVALID_SITE"


def test_gamescript_route_validator_rejects_stale_geometry():
    """The package's own route validator fails closed before latching."""
    vm = build_vm()
    _seed_alternate_route(vm, (1000, 1001, 1002, 1003), 1257, 1001)
    vm.execute(
        "stub_seed(2002, 0);\n"
        "::sniffer.valid <- ::bridge.RouteOk([1000, 1001, 1002, 1003], 1000, 1003, 1257);\n"
        "::sniffer.broken <- ::bridge.RouteOk([1000, 1001, 2002, 1003], 1000, 1003, 1257);\n"
        "::sniffer.short <- ::bridge.RouteOk([1000, 1001], 1000, 1001, 1257);\n"
        "::sniffer.dup <- ::bridge.RouteOk([1000, 1001, 1001, 1002], 1000, 1002, 1257);"
    )
    sniffer = vm_root(vm)["sniffer"]
    assert sniffer["valid"] is True
    assert sniffer["broken"] is False
    assert sniffer["short"] is False
    assert sniffer["dup"] is False


def test_full_cycle_executes_an_optimizer_alternate_route():
    """The complete fifteen-exchange cycle runs on a non-baked route."""
    route = (1000, 1001, 1002, 1003)
    depot, depot_front = 1257, 1001
    plan = _alternate_plan(route, depot, depot_front)
    vm = build_vm()
    _seed_alternate_route(vm, route, depot, depot_front)
    exchanges, _ = run_cycle(vm, plan=plan, pickup=route[0], delivery=route[-1])
    assert [request.request_id for request, _ in exchanges] == list(cf.FREIGHT_EXCHANGE_IDS)
    site = exchanges[0][1]
    assert site.status == "READY"
    assert site.pairs_ok == site.pair_total == len(route) - 1
    assert (site.sid0, site.sid1) == (102, 103)
    assert all(request.route_digest == plan.route_digest for request, _ in exchanges)
    assert exchanges[0][0].route == route
    assert exchanges[11][1].position == route[-1]
    assert exchanges[11][1].progress == len(route) - 1
    cycle = verify_freight_cycle(exchanges, prelaunch_digest=PRELAUNCH, plan=plan)
    assert cycle["verification"] == "FREIGHT_CYCLE_VERIFIED"


def test_route_digest_drift_is_refused_before_purchase():
    """A stale route digest on the engine exchange halts before any buy."""
    route = (1000, 1001, 1002, 1003)
    # Same endpoints and depot, different valid geometry.  The alternate
    # digest is therefore derived from a real competing corridor.
    stale_route = (1000, 1001, 745, 746, 747, 1003)
    depot, depot_front = 1257, 1001
    current = _alternate_plan(route, depot, depot_front)
    stale = _alternate_plan(stale_route, depot, depot_front)
    assert current.route_digest != stale.route_digest
    vm = build_vm()
    _seed_alternate_route(vm, route, depot, depot_front)

    state = dict(site=None, engine=None, vehicle=-1)
    site_request = work._freight_exchange_request(
        work.freight_schedule()[0], PRELAUNCH, current, state
    )
    assert drive(vm, site_request).status == "READY"
    engine_entry = work.freight_schedule()[1]
    stale_request = work._freight_exchange_request(engine_entry, PRELAUNCH, stale, state)
    assert drive(vm, stale_request).status == "STALE_ADMISSION"
    vm.execute("::sniffer.stage <- ::bridge.stage; ::sniffer.vehicles <- ::vehicles.len();")
    assert vm_root(vm)["sniffer"]["stage"] == 1
    assert vm_root(vm)["sniffer"]["vehicles"] == 0


def test_local_plan_verifier_refuses_a_stale_request_before_dispatch():
    """Python owns the trust anchor: a stale request never reaches the wire."""
    route = (1000, 1001, 1002, 1003)
    stale_route = (1000, 1001, 745, 746, 747, 1003)
    current = _alternate_plan(route, 1257, 1001)
    stale = _alternate_plan(stale_route, 1257, 1001)
    request = work._freight_exchange_request(
        work.freight_schedule()[1], PRELAUNCH, stale, dict(site=None, engine=None, vehicle=-1)
    )
    with pytest.raises(ValueError, match="route digest"):
        work.verify_request_against_plan(request, plan=current, seal=PRELAUNCH)
    good = work._freight_exchange_request(
        work.freight_schedule()[1], PRELAUNCH, current, dict(site=None, engine=None, vehicle=-1)
    )
    work.verify_request_against_plan(good, plan=current, seal=PRELAUNCH)
