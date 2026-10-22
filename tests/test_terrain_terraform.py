"""Controlled offline tests for the D3 bounded terraforming wire contract.

The shipped package ``main.nut`` runs inside the real Squirrel VM against a
stub world that reproduces the official shared-point rule of the native
terraform commands; every dispatched reply is parsed back through the same
Python wire contract the production commanding layer uses. Stub knobs
(``::no_op``, ``::quote_reject``, ``::drift``, ``::reject``) inject
controlled native refusals so the fail-closed statuses are exercised against
the shipped package itself, not against a copy of the rules. Nothing here
launches OpenTTD, connects to an AdminPort or writes any native or save
state: only the tests' own VM world is mutated.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from squirrel import SQVM

from app.simulation.openttd.terrain_clearing import TileClass
from app.simulation.openttd.terrain_terraform import (
    SLOPE_N,
    SLOPE_STEEP,
    TerraformExpectation,
    TerraformReadback,
    TerraformRequest,
    TerraformShareState,
    admit_terraform,
    expected_corner_heights,
    terraform_phase_outcome,
    verify_terraform,
)

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "app" / "simulation" / "openttd" / "terrain_terraform_package"
API = REPO / "tests" / "fixtures" / "gamescript_api_15.nut"

PRELAUNCH = "a" * 64
OTHER_PLAN = "b" * 64
SOURCE = "c" * 64

HOST = 48558
WATCHERS = (48558, 48559, 48814, 48815)
SHARED = (175, 190)
MAX_COST = 1000

CORNER_OF = {HOST: "S", 48559: "E", 48814: "W", 48815: "N"}

# Per-tile moved corner and its post-write slope byte (W=1, S=2, E=4, N=8):
# a raise keeps the flat base height, a lower drops the base by one.
RAISED_STATES = ((HOST, "S", 0x2), (48559, "E", 0x4), (48814, "W", 0x1), (48815, "N", 0x8))
LOWERED_STATES = ((HOST, "S", 0xD), (48559, "E", 0xB), (48814, "W", 0xE), (48815, "N", 0x7))

WORLD = """
::dims <- [256, 256];
::tiles <- {};
::funds <- 100000;
::tests <- {};
::account <- 0;
::valid_company <- true;
::mode_ok <- true;
::reject <- false;
::no_op <- false;
::quote_reject <- false;
::drift <- false;
::quote_cost <- 20;
::exec_cost <- 20;
::test_calls <- 0;
::real_calls <- 0;
::base_height <- 1;
::host_owner_override <- -1;
::host_flags_override <- 1;
::host_ridge <- false;
::second_company <- -1;
::sniffer <- {last = "missing"};
"""

WORLD_SEED = """
function seed(tile, el, owner=-1, flags=1) {
    ::tiles[tile] <- {flags=flags, owner=owner, industry=null, c={N=el, E=el, W=el, S=el}};
}
/* Margin region around the four sharing tiles so every edge-read point
 * exists: the S corner of tile 48558 is shared point (175,190). */
for (local y = 187; y <= 193; y++) {
    for (local x = 172; x <= 179; x++) {
        seed(y * 256 + x, ::base_height);
    }
}
::tiles[48558].owner = ::host_owner_override;
::tiles[48558].flags = ::host_flags_override;
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

STUB = """
class GSCompany {
    static COMPANY_INVALID = -1;
    static function ResolveCompanyID(c) {
        return !::valid_company ? -1 : (c == 0 || c == ::second_company) ? c : -1;
    }
    static function GetBankBalance(_) { return ::funds; }
}
class GSCompanyMode {
    constructor(c) { if (c != 0 && c != ::second_company) throw "company"; }
    static function IsValid() { return ::mode_ok; }
}
class GSAccounting {
    constructor() { ::account++; }
    function GetCosts() {
        return (::account in ::tests) ? (::no_op ? 0 : ::quote_cost) : ::exec_cost;
    }
}
class GSTestMode { constructor() { ::tests[::account] <- true; } }
function stub_point_height(px, py) {
    local q = py * ::dims[0] + px;
    if (!(q in ::tiles)) throw "STUB_MISSING_TILE";
    return ::tiles[q].c.N;
}
function stub_shift(t, mask, step) {
    local corner = mask == 8 ? "N" : mask == 4 ? "E" : mask == 1 ? "W" : "S";
    local offs = {N=[0, 0], E=[0, 1], W=[1, 0], S=[1, 1]};
    local tx = t % ::dims[0];
    local ty = t / ::dims[0];
    local px = tx + offs[corner][0];
    local py = ty + offs[corner][1];
    local watchers = [[px, py], [px - 1, py], [px, py - 1], [px - 1, py - 1]];
    if (step > 0) {
        local new_h = stub_point_height(px, py) + step;
        if (new_h > 255) return false;
        foreach (ed in [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
            local e = stub_point_height(px + ed[0], py + ed[1]);
            if (new_h - e > 1 || e - new_h > 1) return false;
        }
    } else {
        local new_h = stub_point_height(px, py) + step;
        if (new_h < 0) return false;
        foreach (ed in [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
            local e = stub_point_height(px + ed[0], py + ed[1]);
            if (new_h - e > 1 || e - new_h > 1) return false;
        }
    }
    foreach (pos in watchers) {
        local qx = pos[0];
        local qy = pos[1];
        local q = qy * ::dims[0] + qx;
        if (!(q in ::tiles)) throw "STUB_MISSING_TILE";
        local c = ::tiles[q].c;
        if (qy == py && qx == px) c.N = c.N + step;
        else if (qy == py && qx == px - 1) c.W = c.W + step;
        else if (qy == py - 1 && qx == px) c.E = c.E + step;
        else if (qy == py - 1 && qx == px - 1) c.S = c.S + step;
    }
    ::funds -= ::exec_cost;
    return true;
}
if (::host_ridge) {
    /* Test-only pre-state: the host tile's N, E and W shared points are
     * pre-raised through the same alias-consistent shift, so the commanded S
     * corner is the tile's last minimum corner (raising it lifts the tile
     * minimum by one). */
    stub_shift(48558, 8, 1);
    stub_shift(48558, 4, 1);
    stub_shift(48558, 1, 1);
    ::funds = 100000;
}
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
    static SLOPE_W = 1;
    static SLOPE_S = 2;
    static SLOPE_E = 4;
    static SLOPE_N = 8;
    static CORNER_N = 3;
    static CORNER_E = 2;
    static CORNER_S = 1;
    static CORNER_W = 0;
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
               (kind == 2 && GSTile.b(t, 11));
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
    static function GetCornerHeight(t, c) {
        local a = ::tiles[t].c;
        return c == 3 ? a.N : c == 2 ? a.E : c == 1 ? a.S : a.W;
    }
    static function RaiseTile(t, mask) {
        if (::account in ::tests) {
            ::test_calls++;
            return ::mode_ok && !::no_op && !::quote_reject;
        }
        ::real_calls++;
        if (::reject) return false;
        if (::drift) {
            local tile = ::tiles[t];
            tile.c.E = tile.c.E + 1;
            ::funds -= ::exec_cost;
            return true;
        }
        return stub_shift(t, mask, 1);
    }
    static function LowerTile(t, mask) {
        if (::account in ::tests) {
            ::test_calls++;
            return ::mode_ok && !::no_op && !::quote_reject;
        }
        ::real_calls++;
        if (::reject) return false;
        if (::drift) {
            local tile = ::tiles[t];
            tile.c.E = tile.c.E + 1;
            ::funds -= ::exec_cost;
            return true;
        }
        return stub_shift(t, mask, -1);
    }
}
class GSRoad {
    static function IsRoadTile(t) { return GSTile.b(t, 7); }
    static function HasRoadType(t, i) { return i == 0 && GSTile.b(t, 9); }
}
class GSAirport {
    static function IsAirportTile(t) { return GSTile.b(t, 12); }
}
class GSIndustry {
    static function GetIndustryID(t) { return ::tiles[t].industry; }
    static function IsValidIndustry(i) { return i != null && i >= 0 && i <= 63999; }
}
"""


def build_vm(**knobs: int | bool) -> SQVM:
    """Fresh VM with the API fixture, the controlled world and the package."""
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
    vm.execute("::bridge <- TerrainTerraformProof();")
    return vm


def vm_root(vm: SQVM) -> dict[str, Any]:
    return vm.get_roottable()


def wire_request(
    op: str,
    request_id: str,
    *,
    plan: str = PRELAUNCH,
    company: int = 0,
    tile: int = HOST,
    corner: str = "S",
    direction: str = "up",
    max_cost: int = MAX_COST,
) -> TerraformRequest:
    return TerraformRequest(
        op=op,
        request_id=request_id,
        plan=plan,
        company=company,
        tile=tile,
        corner=corner,
        direction=direction,
        max_cost=max_cost,
    )


def drive(vm: SQVM, request: TerraformRequest) -> TerraformReadback:
    """Dispatch one request over the wire and parse the reply into Python."""
    replies = vm_root(vm)["replies"]
    before = len(replies)
    vm.execute("::bridge.Handle(" + request.to_bytes().decode() + ");")
    replies = vm_root(vm)["replies"]
    if len(replies) == before:
        raise AssertionError(f"package dropped request {request.request_id}: no reply")
    vm.execute("::sniffer.last = last_reply_json();")
    raw = vm_root(vm)["sniffer"]["last"]
    return TerraformReadback.parse_for(request, raw.encode())


def share_state(
    tile: int,
    corner: str,
    before_min: int,
    after_slope: int,
    *,
    before_slope: int = 0,
    after_min: int = 1,
) -> TerraformShareState:
    return TerraformShareState(
        tile=tile,
        corner=corner,
        before_min_height=before_min,
        before_slope=before_slope,
        after_min_height=after_min,
        after_slope=after_slope,
    )


def expectation_for(
    states: tuple[tuple[int, str, int], ...], direction: str
) -> TerraformExpectation:
    before_min = 1 if direction == "up" else 2
    return TerraformExpectation(
        corner="S",
        corner_mask=0x2,
        direction=direction,
        host_tile=HOST,
        shared_point_x=SHARED[0],
        shared_point_y=SHARED[1],
        sharing_tiles=WATCHERS,
        tiles=tuple(share_state(t, c, before_min, slope) for (t, c, slope) in states),
    )


def raise_expectation() -> TerraformExpectation:
    return expectation_for(RAISED_STATES, "up")


def lower_expectation() -> TerraformExpectation:
    return expectation_for(LOWERED_STATES, "down")


def run_phase(vm: SQVM, exp: TerraformExpectation):
    """Inspect, read the three watchers, admit, execute, no verification."""
    direction = exp.direction
    before = drive(vm, wire_request("inspect", "inspect-1", direction=direction))
    neighbors = [
        drive(
            vm,
            wire_request("read", f"inspect-n{tile}-1", tile=tile, direction=direction),
        )
        for tile in (48559, 48814, 48815)
    ]
    intent = admit_terraform(
        before,
        neighbors,
        exp,
        prelaunch_digest=PRELAUNCH,
        source_save_digest=SOURCE,
        max_cost=MAX_COST,
    )
    built = drive(vm, wire_request("terraform", "terraform-1", direction=direction))
    return before, neighbors, intent, built


def run_cycle(vm: SQVM, exp: TerraformExpectation):
    """Full verified exchange: inspect, reads, admit, execute, reads, verify."""
    before, neighbors, intent, built = run_phase(vm, exp)
    independent = [
        drive(
            vm,
            wire_request("read", f"confirm-{tile}-1", tile=tile, plan=intent.digest),
        )
        for tile in WATCHERS
    ]
    receipt = verify_terraform(intent, before, neighbors, built, independent)
    return before, neighbors, intent, built, independent, receipt


def test_expected_corner_heights_official_derivations():
    assert expected_corner_heights(1, 0) == {"N": 1, "E": 1, "W": 1, "S": 1}
    # Two raised bits (W|S): every reported corner carries the step.
    assert expected_corner_heights(1, 3) == {"N": 1, "E": 1, "W": 2, "S": 2}
    # Steep encoding (N|W|S): the opposite corner is always min_height + 2.
    assert expected_corner_heights(1, 0x1B) == {"N": 2, "E": 1, "W": 3, "S": 2}
    for slope in (0x20, 0x3B):
        with pytest.raises(ValueError, match="halftile slope encodings"):
            expected_corner_heights(1, slope)
    # The steep bit needs exactly three raised corners: 0/1/4 corner bits are
    # encodings no native command can produce and fail closed.
    for slope in (SLOPE_STEEP, SLOPE_STEEP | SLOPE_N, SLOPE_STEEP | 0xF):
        with pytest.raises(ValueError, match="three raised corners"):
            expected_corner_heights(1, slope)


def test_request_model_fails_closed():
    fields = {
        "protocol": 3,
        "op": "inspect",
        "request_id": "bad-op",
        "plan": PRELAUNCH,
        "company": 0,
        "tile": HOST,
        "corner": "S",
        "direction": "up",
        "max_cost": MAX_COST,
    }
    with pytest.raises(ValidationError):
        TerraformRequest.model_validate_json(json.dumps(dict(fields, op="execute")))
    with pytest.raises(ValidationError):
        wire_request("inspect", "Inspect-1", tile=HOST)
    with pytest.raises(ValidationError):
        wire_request("inspect", "plan-bad", tile=HOST, plan="z" * 64)
    with pytest.raises(ValidationError):
        wire_request("inspect", "corner-bad", tile=HOST, corner="Q")
    with pytest.raises(ValidationError):
        wire_request("inspect", "direction-bad", tile=HOST, direction="sideways")
    with pytest.raises(ValidationError):
        wire_request("inspect", "money-bad", tile=HOST, max_cost=-1)
    with pytest.raises(ValidationError):
        wire_request("inspect", "tile-bad", tile=65536)


def noop_reply() -> bytes:
    return json.dumps(
        {
            "protocol": 3,
            "op": "inspect",
            "request_id": "wire-1",
            "plan": PRELAUNCH,
            "company": 0,
            "tile": HOST,
            "corner": "S",
            "direction": "up",
            "status": "STRANGE",
            "flags": 1,
            "industry": None,
            "owner": -1,
            "min_height": 1,
            "slope": 0,
            "h_n": 1,
            "h_e": 1,
            "h_s": 1,
            "h_w": 1,
            "eligible": True,
            "funds": 100000,
            "cost": 20,
        }
    ).encode()


def test_readback_wire_correlation_and_caps():
    request = wire_request("inspect", "wire-1", tile=HOST)
    raw = noop_reply()
    with pytest.raises(ValidationError):
        TerraformReadback.parse_for(request, raw)
    padded = raw.replace(b'"STRANGE"', b'"READ"') + b" " * 520
    with pytest.raises(ValueError, match="exceeds 512 bytes"):
        TerraformReadback.parse_for(request, padded)
    twinned = raw.replace(b'"STRANGE"', b'"NO_OP","status":"NO_OP"')
    with pytest.raises(ValueError, match="duplicate response key"):
        TerraformReadback.parse_for(request, twinned)
    drifted = json.loads(raw)
    drifted["status"] = "READ"
    drifted["corner"] = "N"
    with pytest.raises(ValueError, match="correlation mismatch"):
        TerraformReadback.parse_for(request, json.dumps(drifted).encode())


def test_expectation_ordering_fails_closed():
    with pytest.raises(ValidationError):
        TerraformExpectation(
            corner="S",
            corner_mask=0x3,
            direction="up",
            host_tile=HOST,
            shared_point_x=SHARED[0],
            shared_point_y=SHARED[1],
            sharing_tiles=WATCHERS,
            tiles=tuple(share_state(t, CORNER_OF[t], 1, 0) for t in WATCHERS),
        )
    with pytest.raises(ValidationError):
        TerraformExpectation(
            corner="S",
            corner_mask=0x2,
            direction="up",
            host_tile=HOST,
            shared_point_x=SHARED[0],
            shared_point_y=SHARED[1],
            sharing_tiles=(48559, 48558, 48814, 48815),
            tiles=tuple(share_state(t, CORNER_OF[t], 1, 0) for t in WATCHERS),
        )
    with pytest.raises(ValidationError):
        TerraformExpectation(
            corner="S",
            corner_mask=0x2,
            direction="up",
            host_tile=7,
            shared_point_x=SHARED[0],
            shared_point_y=SHARED[1],
            sharing_tiles=WATCHERS,
            tiles=tuple(share_state(t, CORNER_OF[t], 1, 0) for t in WATCHERS),
        )
    variants = (
        (48558, 48558, 48814, 48815),
        (48559, 48814, 48815),
        (48558, 48559, 48814, 48815, 48559),
    )
    for tiles in variants:
        with pytest.raises(ValidationError):
            TerraformExpectation(
                corner="S",
                corner_mask=0x2,
                direction="up",
                host_tile=HOST,
                shared_point_x=SHARED[0],
                shared_point_y=SHARED[1],
                sharing_tiles=WATCHERS,
                tiles=tuple(
                    share_state(t, CORNER_OF[t], 1, 0x2 if t == HOST else 0) for t in tiles
                ),
            )
    with pytest.raises(ValidationError):
        TerraformShareState(
            tile=HOST,
            corner="S",
            before_min_height=1,
            before_slope=0x40,
            after_min_height=1,
            after_slope=0,
        )


def code_without_comments(text: str) -> str:
    """Source minus line comments and star-prefixed block-comment interiors."""
    out = []
    for line in text.splitlines():
        clean = line.split("//")[0]
        stripped = clean.strip()
        if stripped.startswith("/*") or stripped.startswith("*"):
            continue
        out.append(clean)
    return "\n".join(out)


def test_package_source_keeps_bounded_corner_writes():
    text = (PACKAGE / "main.nut").read_text()
    assert "LevelTiles" not in code_without_comments(text)
    assert "MaskFor" in text


def test_raise_cycle_full_receipt():
    exp = raise_expectation()
    vm = build_vm()
    before, neighbors, intent, built, independent, receipt = run_cycle(vm, exp)
    assert before.status == "READY"
    assert before.corner_heights == (1, 1, 1, 1)
    assert before.classification == TileClass.CLEAR
    assert before.min_height == 1 and before.slope == 0
    assert before.cost == 20 and before.eligible and before.funds == 100000
    assert all(readback.status == "READ" for readback in neighbors)
    assert built.status == "RAISED"
    assert built.corner_heights == (1, 1, 1, 2)
    assert built.cost == 20 and built.funds == 99980
    moved = {
        48558: (1, 1, 1, 2),
        48559: (1, 2, 1, 1),
        48814: (1, 1, 2, 1),
        48815: (2, 1, 1, 1),
    }
    for readback in independent:
        assert readback.status == "READ"
        assert readback.corner_heights == moved[readback.tile]
        assert readback.min_height == 1
    root = vm_root(vm)
    assert root["test_calls"] == 2 and root["real_calls"] == 1
    assert len(receipt) == 24
    assert receipt["schema"] == "company-terraform-receipt-v1"
    assert receipt["operation"] == "TERRAFORM_RAISE"
    assert receipt["native_command"] == "CMD_TERRAFORM_LAND"
    assert receipt["native_quote"] == 20 and receipt["cost"] == 20
    assert receipt["cost_category"] == "terrain-modification"
    assert receipt["execution_status"] == "RAISED"
    assert receipt["verification"] == "NATIVE_STATE_CHANGED"
    assert receipt["error_code"] is None
    assert receipt["company"] == 0 and receipt["tile"] == HOST
    assert (receipt["corner"], receipt["direction"]) == ("S", "up")
    assert (receipt["shared_point_x"], receipt["shared_point_y"]) == SHARED
    assert receipt["corner_mask"] == 0x2
    assert receipt["plan_digest"] == intent.digest
    assert receipt["prelaunch_digest"] == PRELAUNCH
    assert receipt["source_save_digest"] == SOURCE
    assert receipt["before_digest"] == before.digest
    assert receipt["construction_digest"] == built.digest
    assert receipt["after_digests"] == tuple(r.digest for r in independent)
    assert receipt["execution_request_id"] == "terraform-1"
    assert receipt["readback_request_ids"] == tuple(r.request_id for r in independent)


def test_lower_cycle_full_receipt():
    exp = lower_expectation()
    vm = build_vm(base_height=2)
    before, neighbors, intent, built, independent, receipt = run_cycle(vm, exp)
    assert before.status == "READY" and before.corner_heights == (2, 2, 2, 2)
    assert built.status == "LOWERED"
    # Only the commanded S corner fell to the base; the shared point is at 1.
    assert built.corner_heights == (2, 2, 2, 1)
    lowered = {
        48558: (2, 2, 2, 1),
        48559: (2, 1, 2, 2),
        48814: (2, 2, 1, 2),
        48815: (1, 2, 2, 2),
    }
    for readback in independent:
        assert readback.corner_heights == lowered[readback.tile]
        assert readback.min_height == 1
    assert receipt["operation"] == "TERRAFORM_LOWER"
    assert receipt["execution_status"] == "LOWERED"


def test_phase_outcome_reports_complete():
    vm = build_vm()
    before, neighbors, intent, built = run_phase(vm, raise_expectation())
    independent = [
        drive(vm, wire_request("read", f"confirm-{tile}-1", tile=tile, plan=intent.digest))
        for tile in WATCHERS
    ]
    evidence = {
        "intent": intent,
        "before": before,
        "neighbors": neighbors,
        "built": built,
        "independent": independent,
    }
    outcome = terraform_phase_outcome([("single attempt", evidence)])
    assert outcome["schema"] == "terraform-phase-outcome-v1"
    assert outcome["verification"] == "PHASE_COMPLETE"
    assert outcome["failed"] is None and outcome["pending"] == []
    assert len(outcome["completed"]) == 1
    assert outcome["completed"][0]["operation"] == "TERRAFORM_RAISE"


def test_admission_refuses_zero_cost_no_op():
    vm = build_vm(no_op=True)
    before = drive(vm, wire_request("inspect", "inspect-noop"))
    assert before.status == "NO_OP" and before.cost == 0
    with pytest.raises(ValueError, match="no admissible change"):
        admit_terraform(
            before,
            [],
            raise_expectation(),
            prelaunch_digest=PRELAUNCH,
            source_save_digest=SOURCE,
            max_cost=MAX_COST,
        )


def test_admission_refuses_refused_quote():
    vm = build_vm(quote_reject=True)
    before = drive(vm, wire_request("inspect", "inspect-reject"))
    assert before.status == "REJECTED" and before.cost == 20
    with pytest.raises(ValueError, match="native classified-clear"):
        admit_terraform(
            before,
            [],
            raise_expectation(),
            prelaunch_digest=PRELAUNCH,
            source_save_digest=SOURCE,
            max_cost=MAX_COST,
        )


def test_ceiling_and_funds_statuses():
    over = drive(build_vm(quote_cost=30000), wire_request("inspect", "inspect-cap"))
    assert over.status == "COST_LIMIT" and over.cost == 30000
    broke = drive(build_vm(funds=10), wire_request("inspect", "inspect-broke"))
    assert broke.status == "INSUFFICIENT_FUNDS"
    equal = drive(build_vm(quote_cost=10), wire_request("inspect", "inspect-eq", max_cost=10))
    assert equal.status == "READY" and equal.cost == 10


def test_native_fact_outside_contract_fails_closed():
    vm = build_vm(host_owner_override=20)
    bad = drive(vm, wire_request("inspect", "inspect-native"))
    assert bad.status == "UNSUPPORTED_NATIVE_FACT"
    assert bad.owner == -1
    again = drive(vm, wire_request("read", "read-native"))
    assert again.status == "UNSUPPORTED_NATIVE_FACT"


def test_forbidden_class_refused_before_quote():
    vm = build_vm(host_flags_override=0x2001)
    house = drive(vm, wire_request("inspect", "inspect-house"))
    assert house.status == "FORBIDDEN_CLASS"
    assert vm_root(vm)["test_calls"] == 0


def test_ownership_mismatch_refused():
    vm = build_vm(host_owner_override=1)
    seen = drive(vm, wire_request("inspect", "inspect-owned"))
    assert seen.status == "OWNERSHIP_MISMATCH"
    assert seen.owner == 1 and not seen.eligible


def test_stale_admission_guards():
    built = drive(build_vm(), wire_request("terraform", "terraform-early"))
    assert built.status == "STALE_ADMISSION"

    vm = build_vm()
    drive(vm, wire_request("inspect", "inspect-seal-1"))
    built = drive(vm, wire_request("terraform", "terraform-foreign-plan", plan=OTHER_PLAN))
    assert built.status == "STALE_ADMISSION"

    vm = build_vm()
    drive(vm, wire_request("inspect", "inspect-seal-2"))
    vm.execute("::tiles[48558].c.N = ::tiles[48558].c.N + 1;")
    built = drive(vm, wire_request("terraform", "terraform-drifted"))
    assert built.status == "STALE_ADMISSION"


def test_one_shot_attempt_latch():
    vm = build_vm()
    run_cycle(vm, raise_expectation())
    slammed = drive(vm, wire_request("inspect", "inspect-after-1"))
    assert slammed.status == "ALREADY_ATTEMPTED"
    built = drive(vm, wire_request("terraform", "terraform-2"))
    assert built.status == "ALREADY_ATTEMPTED"
    observed = drive(vm, wire_request("read", "read-after-1"))
    assert observed.status == "READ"


def test_execution_cost_divergence_disagrees():
    vm = build_vm(exec_cost=25)
    before, neighbors, intent, built = run_phase(vm, raise_expectation())
    assert built.cost == 25 and built.funds == 99975
    with pytest.raises(ValueError, match="tested cost disagreement"):
        verify_terraform(
            intent,
            before,
            neighbors,
            built,
            [
                drive(vm, wire_request("read", f"confirm-{t}-1", tile=t, plan=intent.digest))
                for t in WATCHERS
            ],
        )


def test_failed_command_preserved_uncertainty():
    vm = build_vm(reject=True)
    before, neighbors, intent, built = run_phase(vm, raise_expectation())
    assert built.status == "REJECTED"
    assert built.cost == 20 and built.funds == before.funds
    assert vm_root(vm)["real_calls"] == 1
    with pytest.raises(ValueError, match="tested cost disagreement"):
        verify_terraform(intent, before, neighbors, built, [])
    outcome = terraform_phase_outcome(
        [
            (
                "attempt one",
                {
                    "intent": intent,
                    "before": before,
                    "neighbors": neighbors,
                    "built": built,
                },
            ),
            ("attempt two", {"intent": None, "before": None, "neighbors": None, "built": None}),
        ]
    )
    assert outcome["verification"] == "PARTIAL_EXECUTION_EVIDENCE"
    assert outcome["completed"] == []
    assert outcome["failed"]["label"] == "attempt one"
    assert outcome["failed"]["world_state"] == "UNCERTAIN_AFTER_FAILED_COMMAND"
    assert outcome["pending"] == ["attempt two"]


def test_native_drift_reports_readback_mismatch():
    vm = build_vm(drift=True)
    before, neighbors, intent, built = run_phase(vm, raise_expectation())
    assert built.status == "READBACK_MISMATCH"
    assert built.corner_heights == (1, 2, 1, 1)
    assert built.funds == 99980
    with pytest.raises(ValueError, match="tested cost disagreement"):
        verify_terraform(intent, before, neighbors, built, [])
    outcome = terraform_phase_outcome(
        [
            (
                "drifting attempt",
                {
                    "intent": intent,
                    "before": before,
                    "neighbors": neighbors,
                    "built": built,
                },
            )
        ]
    )
    assert outcome["failed"]["label"] == "drifting attempt"
    assert outcome["failed"]["world_state"] == "UNCERTAIN_AFTER_FAILED_COMMAND"
    assert outcome["verification"] == "PARTIAL_EXECUTION_EVIDENCE"


def test_mid_cycle_funds_drift_reveals_spent_funds():
    vm = build_vm()
    before, neighbors, intent, built = run_phase(vm, raise_expectation())
    assert built.status == "RAISED"
    vm.execute("::funds = ::funds - 100;")
    independent = [
        drive(vm, wire_request("read", f"confirm-{tile}-1", tile=tile, plan=intent.digest))
        for tile in WATCHERS
    ]
    assert all(readback.funds == 99880 for readback in independent)
    with pytest.raises(ValueError, match="reveals spent funds"):
        verify_terraform(intent, before, neighbors, built, independent)


def test_independent_reads_must_be_intent_scoped():
    vm = build_vm()
    before, neighbors, intent, built = run_phase(vm, raise_expectation())
    independent = [
        drive(
            vm,
            wire_request(
                "read",
                f"confirm-{tile}-1",
                tile=tile,
                plan=intent.digest if tile != 48815 else PRELAUNCH,
            ),
        )
        for tile in WATCHERS
    ]
    with pytest.raises(ValueError, match="intent-scoped"):
        verify_terraform(intent, before, neighbors, built, independent)


def test_request_counter_cap_covers_the_full_budget():
    """The dispatcher must accept every exchange of a maximum-budget plan.

    The reviewed budget admits 32 corner ops; one op consumes 9 wire
    exchanges, so the accepted-request counter must reach 32 * 9 + slack
    before refusing - a smaller cap would strand a budgeted plan mid-phase.
    """
    vm = build_vm()
    for i in range(296):
        reply = drive(vm, wire_request("read", f"cap-{i:03d}"))
        assert reply.status == "READ"
    with pytest.raises(AssertionError, match="dropped"):
        drive(vm, wire_request("read", "cap-296"))


def test_wire_shape_fail_closed_drops():
    vm = build_vm()
    base = {
        "protocol": 3,
        "op": "inspect",
        "request_id": "drop-1",
        "plan": PRELAUNCH,
        "company": 0,
        "tile": HOST,
        "corner": "S",
        "direction": "up",
        "max_cost": MAX_COST,
    }
    before = len(vm_root(vm)["replies"])
    for mutate in (
        {"op": "execute"},
        {"request_id": "a" * 33},
        {"request_id": "A-1"},
        {"plan": "A" * 64},
        {"plan": "x" * 63},
        {"corner": "SS"},
        {"direction": "sideways"},
        {"max_cost": -1},
        {"tile": 65536},
        {"company": "zero"},
    ):
        payload = dict(base, **mutate)
        vm.execute("::bridge.Handle(" + json.dumps(payload) + ");")
    assert len(vm_root(vm)["replies"]) == before


def test_used_request_ids_are_never_replayed():
    vm = build_vm()
    first = drive(vm, wire_request("inspect", "inspect-seal-3"))
    assert first.status == "READY"
    before = len(vm_root(vm)["replies"])
    vm.execute(
        "::bridge.Handle(" + wire_request("inspect", "inspect-seal-3").to_bytes().decode() + ");"
    )
    assert len(vm_root(vm)["replies"]) == before


def test_response_round_trip_is_canonical_bytes():
    request = wire_request("terraform", "roundtrip-1")
    raw = request.to_bytes()
    assert len(raw) <= 512
    assert TerraformRequest.model_validate_json(raw.decode()) == request
    assert raw.startswith(b'{"company":0,')
    assert json.loads(raw.decode())["request_id"] == "roundtrip-1"


def test_readback_funds_bounds_mirror_the_wire():
    """The funds/cost fields mirror the dispatcher's TERRAFORM bounds.

    The package refuses reported funds outside the signed 32-bit range before
    send-time, so an accepted-in-Python readback cannot exceed that window
    either.
    """
    request = wire_request("inspect", "wire-funds")
    vm = build_vm()
    drive(vm, request)
    body = json.loads(vm_root(vm)["sniffer"]["last"])
    assert body["company"] == request.company
    body["funds"] = 2**31
    with pytest.raises(ValidationError):
        TerraformReadback.parse_for(request, json.dumps(body).encode())
    body["funds"] = 100000
    assert TerraformReadback.parse_for(request, json.dumps(body).encode()).status == "READY"


def test_independent_reads_must_carry_the_admitted_company():
    vm = build_vm()
    before, neighbors, intent, built = run_phase(vm, raise_expectation())
    independent = [
        drive(vm, wire_request("read", f"confirm-{tile}-1", tile=tile, plan=intent.digest))
        for tile in WATCHERS
    ]
    independent[1] = independent[1].model_copy(update={"company": 1})
    with pytest.raises(ValueError, match="intent-scoped"):
        verify_terraform(intent, before, neighbors, built, independent)


def test_admission_rejects_malformed_neighbor_evidence():
    exp = raise_expectation()
    vm = build_vm()
    before = drive(vm, wire_request("inspect", "inspect-ev"))
    neighbors = [
        drive(vm, wire_request("read", f"inspect-nev-{tile}", tile=tile))
        for tile in (48559, 48814, 48815)
    ]
    with pytest.raises(ValueError, match="must be freshly observed"):
        admit_terraform(
            before,
            [],
            exp,
            prelaunch_digest=PRELAUNCH,
            source_save_digest=SOURCE,
            max_cost=MAX_COST,
        )
    with pytest.raises(ValueError, match="correlated inspection read"):
        admit_terraform(
            before,
            [neighbors[0], neighbors[1], neighbors[2].model_copy(update={"plan": OTHER_PLAN})],
            exp,
            prelaunch_digest=PRELAUNCH,
            source_save_digest=SOURCE,
            max_cost=MAX_COST,
        )


def test_foreign_company_terraform_is_stale():
    vm = build_vm(second_company=1)
    drive(vm, wire_request("inspect", "inspect-c0"))
    built = drive(vm, wire_request("terraform", "terraform-c1", company=1))
    assert built.status == "STALE_ADMISSION"
    assert vm_root(vm)["real_calls"] == 0


def test_phase_outcome_preserves_completed_receipts():
    vm = build_vm()
    before, neighbors, intent, built = run_phase(vm, raise_expectation())
    independent = [
        drive(vm, wire_request("read", f"confirm-{tile}-1", tile=tile, plan=intent.digest))
        for tile in WATCHERS
    ]
    good = {
        "intent": intent,
        "before": before,
        "neighbors": neighbors,
        "built": built,
        "independent": independent,
    }
    bad = {"intent": None, "before": None, "neighbors": None, "built": None}
    outcome = terraform_phase_outcome([("good attempt", good), ("failed attempt", bad)])
    assert outcome["completed"][0]["schema"] == "company-terraform-receipt-v1"
    assert outcome["failed"]["label"] == "failed attempt"
    assert outcome["failed"]["world_state"] == "UNCERTAIN_AFTER_FAILED_COMMAND"
    assert outcome["verification"] == "PARTIAL_EXECUTION_EVIDENCE"
    assert outcome["pending"] == []
    # Reversed order: the failure halts the phase and the later attempt is
    # reported as pending, never executed or implied.
    retried = terraform_phase_outcome([("failed attempt", bad), ("good attempt", good)])
    assert retried["completed"] == []
    assert retried["failed"]["label"] == "failed attempt"
    assert retried["pending"] == ["good attempt"]


def test_raise_last_minimum_corner_still_certifies():
    """Raising the host's last minimum corner lifts the tile minimum by one.

    The pinned inventory forces exactly this shape eight times: the host tile's
    E corner already sits one above the others, so the raise on the shared
    point turns the tile flat one step higher. The dispatcher must certify the
    derived after-state instead of reporting a readback mismatch."""
    vm = build_vm(host_ridge=True)
    exp = TerraformExpectation(
        corner="S",
        corner_mask=0x2,
        direction="up",
        host_tile=HOST,
        shared_point_x=SHARED[0],
        shared_point_y=SHARED[1],
        sharing_tiles=WATCHERS,
        tiles=(
            share_state(HOST, "S", 1, 0, before_slope=0xD, after_min=2),
            share_state(48559, "E", 1, 0xC, before_slope=0x8),
            share_state(48814, "W", 1, 0x9, before_slope=0x8),
            share_state(48815, "N", 1, 0x8, before_slope=0),
        ),
    )
    before, neighbors, intent, built = run_phase(vm, exp)
    assert before.status == "READY"
    assert (before.min_height, before.slope) == (1, 0xD)
    assert built.status == "RAISED"
    assert built.corner_heights == (2, 2, 2, 2)
    assert (built.min_height, built.slope) == (2, 0)
    independent = [
        drive(vm, wire_request("read", f"confirm-{tile}-1", tile=tile, plan=intent.digest))
        for tile in WATCHERS
    ]
    receipt = verify_terraform(intent, before, neighbors, built, independent)
    assert receipt["verification"] == "NATIVE_STATE_CHANGED"
    moved = {48558: (2, 2, 2, 2), 48559: (2, 2, 1, 1), 48814: (2, 1, 2, 1), 48815: (2, 1, 1, 1)}
    for readback in independent:
        assert readback.corner_heights == moved[readback.tile]
