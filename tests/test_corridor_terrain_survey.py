"""Controlled offline tests for the protocol-7 terrain-survey wire contract
(D5-TERRAIN-SURVEY-1, consumed; now the D5-CORRIDOR-EXTENSION-3-SURVEY-1 pins).

The contract under test is ``app/simulation/openttd/corridor_terrain_survey.py``
and the additive protocol-7 terrain handler shipped inside
``app/simulation/openttd/d5_freight_package/main.nut``. As with
``tests/test_corridor_accept_survey.py``, the shipped package runs inside the
real Squirrel VM against the stub freight world; every dispatched reply is
parsed back through the protocol-7 wire contract, never through the package's
own words.

Additivity: the terrain handler is dispatched as ``TerrainHandle`` on the same
``D5FreightProof`` bridge object; the freight (protocol 5) and acceptance
survey (protocol 6) ``Handle`` paths, their stubs, their schedules and their
latches stay untouched here. The only stub surface this file adds is a
``GSTile`` subclass carrying the terrain fact predicates the terrain tile op
reads natively (slope/heights/buildable/owner, the tree/water/coast/farm/rock/
rough obstruction predicates and the four transport presences); every parent
``GSTile`` member the freight and survey paths read is inherited unchanged.

Source-shape finding of record (2026-10-29): the terrain handling briefly
compared ``typeof`` values to the literal ``"boolean"`` before this suite
proved Squirrel's ``typeof`` for booleans is ``"bool"`` (the same string the
package's own protocol-5/6 guards compare against); with that spelling no
tile-fact set could ever guard through to a READY reply and the throw
escaped ``TerrainHandle`` entirely. The shipped package has been corrected
upstream to ``"bool"``, the suite boots the verbatim shipped source
(``PATCHED_SRC`` is now the same bytes), and the deadlock regression is
recorded by the shipped-shape pin below instead of the old in-memory patch.

Binary safety: every test here is strictly offline — nothing launches
OpenTTD, connects to an AdminPort, stages a candidate, writes a claim or an
authorization, or touches any save or native state. The survey itself may only
ever execute later under a fresh, explicit operator authorization.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from squirrel import SQVM

from app.simulation.openttd.corridor_accept_survey import FUNDS_AT_D4_CLOSE
from app.simulation.openttd.corridor_terrain_survey import (
    MAX_TERRAIN_REQUEST_BYTES,
    MAX_TERRAIN_RESPONSE_BYTES,
    PLANNED_TERRAIN_EXCHANGES,
    TERRAIN_ACCEPT_CONTROL_TILE,
    TERRAIN_ACCEPT_STOP_TILE,
    TERRAIN_ACCEPT_TILES,
    TERRAIN_COMPANY,
    TERRAIN_EXCHANGE_IDS,
    TERRAIN_REQUEST_BUDGET,
    TERRAIN_TILES,
    TerrainReadback,
    TerrainRequest,
    terrain_survey_plan,
    verify_request_against_terrain_survey_plan,
)
from tests.test_corridor_accept_survey import freight_site_request
from tests.test_corridor_freight import PACKAGE
from tests.test_corridor_freight import build_vm as _freight_build_vm

SEAL = "c" * 64
FUNDS = 492149

# The shipped package source: the two terrain ``typeof "bool"`` spellings are
# the live (corrected) ones; PATCHED_SRC stays verbatim.
PACKAGE_SRC = (PACKAGE / "main.nut").read_text()
DEAD_TOKEN = '"boolean"'
DEAD_COUNT = PACKAGE_SRC.count(DEAD_TOKEN)
assert DEAD_COUNT in (0, 2), "terrain typeof spelling drifted"
# The only in-memory delta (when needed): the two dead tokens, corrected to
# Squirrel's own typeof name for booleans ('bool', identical to the
# protocol-5/6 guards' spelling).
PATCHED_SRC = PACKAGE_SRC.replace(DEAD_TOKEN, '"bool"') if DEAD_COUNT else PACKAGE_SRC
NEEDS_PATCH = DEAD_COUNT == 2

# The pinned terrain schedule: (exchange, op, tile-of-record).
SCHEDULE: tuple[tuple[str, str, int | None], ...] = (
    ("radius-00", "radius", None),
    ("tile-00", "tile", TERRAIN_TILES[0]),
    ("tile-01", "tile", TERRAIN_TILES[1]),
    ("tile-02", "tile", TERRAIN_TILES[2]),
    ("tile-03", "tile", TERRAIN_TILES[3]),
    ("tile-04", "tile", TERRAIN_TILES[4]),
    ("tile-05", "tile", TERRAIN_TILES[5]),
    ("tile-06", "tile", TERRAIN_TILES[6]),
    ("accept-00", "accept", TERRAIN_ACCEPT_CONTROL_TILE),
    ("accept-01", "accept", TERRAIN_ACCEPT_STOP_TILE),
)
OP_BY_EXCHANGE = {exchange: op for exchange, op, _tile in SCHEDULE}

TERRAIN_FACT_WORLD = """
/* Terrain fact stub surface: a GSTile subclass carrying exactly the members
 * the terrain tile op reads natively and inheriting everything the freight
 * and survey paths read. ::fact_ints selects the integer-returning variant
 * of the fact Predicates (some native layers surface integers); both the
 * boolean and integer variants observe TilePinned by TERRA_TILES pins. */
::fact_ints <- false;
::terrain_facts <- {};
::terrain_facts[50095] <- {slope = 0, minh = 0, maxh = 0};
::terrain_facts[50096] <- {slope = 0, minh = 0, maxh = 0};
::terrain_facts[50352] <- {slope = 0, minh = 0, maxh = 0};
::terrain_facts[50608] <- {slope = 0, minh = 0, maxh = 0};
/* The documented D5-CORRIDOR-EXTENSION-1 finding: live slope on the
 * predecessor's terrace stop tile — a FINDING of record, never a failure. */
::terrain_facts[50864] <- {slope = 9, minh = 0, maxh = 8};
::terrain_facts[50863] <- {slope = 0, minh = 0, maxh = 0};
::terrain_facts[50862] <- {slope = 0, minh = 0, maxh = 0};
foreach (t in [50096, 50352, 50608, 50864, 50863, 50862]) {
    if (!(t in ::tiles)) ::tiles[t] <- {flags = 0x0280, owner = 0};
}
class GSTileTerrain extends GSTile {
    static TRANSPORT_ROAD = 0;
    static TRANSPORT_RAIL = 1;
    static TRANSPORT_WATER = 2;
    static TRANSPORT_AIR = 3;
    static function GetSlope(t) { return ::terrain_facts[t].slope; }
    static function GetMinHeight(t) { return ::terrain_facts[t].minh; }
    static function GetMaxHeight(t) { return ::terrain_facts[t].maxh; }
    static function IsBuildable(t) { return ::fact_ints ? 1 : true; }
    static function HasTreeOnTile(t) { return ::fact_ints ? 0 : false; }
    static function IsWaterTile(t) { return ::fact_ints ? 0 : false; }
    static function IsCoastTile(t) { return ::fact_ints ? 0 : false; }
    static function IsFarmTile(t) { return ::fact_ints ? 0 : false; }
    static function IsRockTile(t) { return ::fact_ints ? 0 : false; }
    static function IsRoughTile(t) { return ::fact_ints ? 0 : false; }
    static function HasTransportType(t, kind) {
        local road = kind == GSTileTerrain.TRANSPORT_ROAD && t == 50095;
        return ::fact_ints ? (road ? 1 : 0) : road;
    }
}
::GSTile = GSTileTerrain;
function terrain_fact_types() {
    local r = ::replies[::replies.len() - 1];
    local out = "";
    foreach (k in ["radius", "tile", "slope", "min_height", "max_height",
                   "buildable", "owner", "tree", "water", "coast", "farm",
                   "rock", "rough", "road", "rail", "water_transport",
                   "air_transport", "accept", "funds", "cost"]) {
        if (!(k in r)) continue;
        if (out.len() > 0) out = out + ",";
        out = out + k + ":" + typeof r[k];
    }
    return out;
}
"""


def shipped_vm() -> SQVM:
    """Fresh VM with the shipped (uncorrected) bridge and the fact stubs."""
    world = _freight_build_vm()
    world.execute(TERRAIN_FACT_WORLD)
    return world


def corrected_vm() -> SQVM:
    """Fresh VM whose ::bridge is booted from the shipped source as-is, or —
    while the two dead typeof spellings remain shipped — from that source
    with only those two tokens corrected in memory (asserted below)."""
    world = _freight_build_vm()
    world.execute(TERRAIN_FACT_WORLD)
    world.execute(PATCHED_SRC)
    world.execute("::bridge <- D5FreightProof();")
    return world


def set_global(world: SQVM, assignment: str) -> None:
    world.execute("::" + assignment)


def order(exchange: str, tile: int | None) -> TerrainRequest:
    plan = terrain_survey_plan()
    return TerrainRequest(
        op=OP_BY_EXCHANGE[exchange],
        request_id=exchange,
        plan=SEAL,
        company=plan.company,
        max_cost=0,
        pickup=plan.pickup,
        delivery=plan.delivery,
        depot=plan.depot,
        tile=tile,
    )


def rerolled(exchange: str, tile: int | None, **changes) -> TerrainRequest:
    """A terrain request outside the fixed schedule (drifted or malformed)."""
    req = order(exchange, tile)
    return TerrainRequest.model_validate({**req.model_dump(exclude_none=True), **changes})


def probe_request(op: str, request_id: str, tile: int | None) -> TerrainRequest:
    """A hand-built body-shaped request whose bytes bypass the Python pins."""
    return TerrainRequest.model_construct(
        op=op,
        request_id=request_id,
        plan=SEAL,
        company=0,
        max_cost=0,
        pickup=45748,
        delivery=50351,
        depot=45487,
        tile=tile,
    )


def terrain_drive(world: SQVM, req: TerrainRequest) -> TerrainReadback:
    world.execute("::bridge.TerrainHandle(" + req.to_bytes().decode() + ");")
    world.execute("::sniffer.last = last_reply_json();")
    raw = world.get_roottable()["sniffer"]["last"].encode()
    assert len(raw) <= MAX_TERRAIN_RESPONSE_BYTES
    return TerrainReadback.parse_for(req, raw)


def fact_types(world: SQVM) -> str:
    """`field:typeof` list of the last dispatched reply table (Squirrel truth)."""
    world.execute("::sniffer.last = terrain_fact_types();")
    return world.get_roottable()["sniffer"]["last"]


def dropped(world: SQVM, req: TerrainRequest) -> None:
    before = len(world.get_roottable()["replies"])
    world.execute("::bridge.TerrainHandle(" + req.to_bytes().decode() + ");")
    assert len(world.get_roottable()["replies"]) == before  # silently dropped


def run_schedule(world: SQVM) -> list[TerrainReadback]:
    return [terrain_drive(world, order(exchange, tile)) for exchange, _op, tile in SCHEDULE]


# --- plan, schedule pins and the wire contract (offline) ---------------------


def test_terrain_plan_pins_the_controlled_world_and_schedule():
    plan = terrain_survey_plan()
    assert plan.company == TERRAIN_COMPANY == 0 and plan.cargo == 1
    assert (plan.pickup, plan.pickup_front) == (45748, 45747)
    assert (plan.delivery, plan.delivery_front) == (50351, 50095)
    assert (plan.depot, plan.depot_front) == (45487, 45743)
    assert plan.expected_funds == FUNDS_AT_D4_CLOSE == FUNDS
    assert plan.request_budget == TERRAIN_REQUEST_BUDGET == 32
    assert (TERRAIN_ACCEPT_CONTROL_TILE, TERRAIN_ACCEPT_STOP_TILE) == (50351, 50862)
    assert TERRAIN_ACCEPT_TILES == (50351, 50862)
    assert (
        plan.schedule
        == TERRAIN_EXCHANGE_IDS
        == tuple(exchange for exchange, _op, _tile in SCHEDULE)
    )
    assert len(plan.terra_tiles) == len(TERRAIN_TILES) == 7
    assert PLANNED_TERRAIN_EXCHANGES == 10


def test_shipped_terrain_source_pins_schedule_tiles_and_budget():
    """The shipped main.nut pins the same ten-exchange schedule, the same
    TERRA_TILES observation set and acceptance pair, and the shared 32-request
    budget the contract module type-checks."""
    for exchange, op, _tile in SCHEDULE:
        assert '["' + exchange + '", "' + op + '", "READY"]' in PACKAGE_SRC
    assert "TERRA_TILES = [50095, 50096, 50352, 50608, 50864, 50863, 50862]" in PACKAGE_SRC
    assert "TERRA_ACCEPT_CONTROL = 50351" in PACKAGE_SRC
    assert "TERRA_ACCEPT_STOP = 50862" in PACKAGE_SRC
    assert "max_requests = 32" in PACKAGE_SRC
    assert "protocol = 7" in PACKAGE_SRC and "protocol = 6" in PACKAGE_SRC
    assert "terrain_halted" in PACKAGE_SRC


def test_terrain_requests_are_canonical_bounded_and_plan_bound():
    raw = order("tile-00", TERRAIN_TILES[0]).to_bytes()
    assert raw.decode() == (
        '{"company":0,"delivery":50351,"depot":45487,"max_cost":0,"op":"tile",'
        '"pickup":45748,"plan":"' + SEAL + '","protocol":7,'
        '"request_id":"tile-00","tile":50095}'
    )
    assert len(raw) < MAX_TERRAIN_REQUEST_BYTES
    assert len(order("radius-00", None).to_bytes()) < MAX_TERRAIN_REQUEST_BYTES
    plan = terrain_survey_plan()
    for exchange, _op, tile in SCHEDULE:
        verify_request_against_terrain_survey_plan(order(exchange, tile), plan=plan, seal=SEAL)
    with pytest.raises(ValueError, match="staged prelaunch seal"):
        verify_request_against_terrain_survey_plan(
            order("tile-00", TERRAIN_TILES[0]), plan=plan, seal="d" * 64
        )
    with pytest.raises(ValueError, match="drifted|planned"):
        verify_request_against_terrain_survey_plan(
            rerolled("tile-00", TERRAIN_TILES[1]), plan=plan, seal=SEAL
        )


def good_tile_readback_dumps() -> dict:
    return TerrainReadback.model_validate(
        {
            "protocol": 7,
            "op": "tile",
            "request_id": "tile-00",
            "plan": SEAL,
            "company": 0,
            "max_cost": 0,
            "pickup": 45748,
            "delivery": 50351,
            "depot": 45487,
            "tile": 50095,
            "status": "READY",
            "funds": FUNDS,
            "cost": 0,
            "slope": 0,
            "min_height": 0,
            "max_height": 0,
            "buildable": True,
            "owner": 0,
            "tree": False,
            "water": False,
            "coast": False,
            "farm": False,
            "rock": False,
            "rough": False,
            "road": True,
            "rail": False,
            "water_transport": False,
            "air_transport": False,
        }
    ).model_dump()


def test_terrain_readbacks_refuse_hybrid_and_out_of_range_observations():
    good = good_tile_readback_dumps()
    with pytest.raises(ValidationError, match="unclaimed observation set"):
        TerrainReadback.model_validate({**good, "status": "INVALID_LOCATION"})
    with pytest.raises(ValidationError, match="slope"):
        TerrainReadback.model_validate({**good, "slope": 256})
    with pytest.raises(ValidationError, match="radius"):
        TerrainReadback.model_validate({**good, "radius": 256})
    with pytest.raises(ValidationError, match="owner"):
        TerrainReadback.model_validate({**good, "owner": -3})


def test_terrain_fact_norm_and_guard_deadlock_through_the_shipped_bridge():
    """Finding of record: with the shipped ``typeof == "boolean"`` spellings
    (Squirrel reports ``bool``), a TerrainTileOp READY reply can never guard
    through: boolean stub facts escape TerrainHandle as D5_NATIVE_FACT from
    TerrainFactNorm, and integer stub facts reach D5_RESPONSE_OUT_OF_BOUNDS
    after normalization converts them to booleans. Skipped once the shipped
    source is corrected upstream."""
    if not NEEDS_PATCH:  # pragma: no cover - corrected source resumed upstream
        pytest.skip("shipped terrain source already corrects the typeof spelling")
    # Boolean stub facts.
    world = shipped_vm()
    with pytest.raises(RuntimeError, match="D5_NATIVE_FACT"):
        world.execute(
            "::bridge.TerrainHandle(" + order("radius-00", None).to_bytes().decode() + ");"
        )
        world.execute(
            "::bridge.TerrainHandle("
            + order("tile-00", TERRAIN_TILES[0]).to_bytes().decode()
            + ");"
        )
    assert len(world.get_roottable()["replies"]) == 1  # radius only
    # Integer stub facts: normalized 0/1 become Squirrel booleans and the
    # shipped guard refuses the normalized set by the same dead spelling.
    world = shipped_vm()
    set_global(world, "fact_ints = true;")
    with pytest.raises(RuntimeError, match="D5_RESPONSE_OUT_OF_BOUNDS"):
        world.execute(
            "::bridge.TerrainHandle(" + order("radius-00", None).to_bytes().decode() + ");"
        )
        world.execute(
            "::bridge.TerrainHandle("
            + order("tile-00", TERRAIN_TILES[0]).to_bytes().decode()
            + ");"
        )
    assert len(world.get_roottable()["replies"]) == 1  # radius only


# --- the shipped structure: the corrected-source terrain dispatch ------------


def test_shipped_source_carries_the_alive_bool_spellings():
    """The upstream correction landed in the shipped package: the two
    terrain typeof spellings are Squirrel's ``"bool"`` and every handler
    structure, status literal, budget cap and pin is the shipped source."""
    assert DEAD_COUNT == 0
    assert PATCHED_SRC == PACKAGE_SRC
    assert 'typeof r[pred] != "bool"' in PACKAGE_SRC
    assert 'typeof r[pred] == "integer"' in PACKAGE_SRC
    assert DEAD_TOKEN not in PACKAGE_SRC
    # The shipped protocol-5/6 guard spellings remain untouched.
    assert 'typeof r.paused != "bool"' in PACKAGE_SRC


def test_handler_runs_the_full_pinned_ten_exchange_schedule():
    replies = run_schedule(corrected_vm())
    for reply in replies:
        assert reply.status == "READY"
        assert reply.funds == FUNDS
        assert reply.cost == 0


def test_handler_measures_the_stub_funds_radius_and_tile_facts():
    world = corrected_vm()
    radius = terrain_drive(world, order("radius-00", None))
    assert (radius.status, radius.radius, radius.funds) == ("READY", 8, FUNDS)
    assert radius.tile is None and radius.slope is None
    # 50095 is the built delivery front carrying the company-road fact.
    first = terrain_drive(world, order("tile-00", TERRAIN_TILES[0]))
    assert (first.status, first.tile) == ("READY", TERRAIN_TILES[0])
    assert (first.slope, first.min_height, first.max_height) == (0, 0, 0)
    assert first.buildable is True and first.owner == 0
    assert (first.tree, first.water, first.coast) == (False, False, False)
    assert (first.farm, first.rock, first.rough) == (False, False, False)
    assert first.road is True
    assert (first.rail, first.water_transport, first.air_transport) == (
        False,
        False,
        False,
    )
    # The dispatched reply table carries Squirrel booleans and integers.
    types = fact_types(world)
    for expected in (
        "slope:integer",
        "min_height:integer",
        "max_height:integer",
        "buildable:bool",
        "owner:integer",
        "tree:bool",
        "water:bool",
        "coast:bool",
        "farm:bool",
        "rock:bool",
        "rough:bool",
        "road:bool",
        "rail:bool",
        "water_transport:bool",
        "air_transport:bool",
        "funds:integer",
        "cost:integer",
    ):
        assert expected in types
    # The terrace stop tile keeps the live-slope FINDING of record.
    finding = None
    for exchange, _op, tile in SCHEDULE[2:6]:
        finding = terrain_drive(world, order(exchange, tile))
        assert finding.status == "READY"
        assert finding.tile == tile
    assert (finding.slope, finding.min_height, finding.max_height) == (9, 0, 8)


def test_handler_measures_the_proposed_station_ground_tile_50862():
    """The one tile this survey adds over the consumed instrument: the
    proposed station ground 50862 (scheduled exchange tile-06) is observed
    with its full fact set through the same shipped handler."""
    world = corrected_vm()
    assert terrain_drive(world, order("radius-00", None)).status == "READY"
    # tile-06 is scheduled after tile-05; walk the schedule in plan order.
    run = run_schedule(corrected_vm())
    pick = run[7]
    assert (pick.status, pick.tile, pick.op) == ("READY", 50862, "tile")
    assert (pick.slope, pick.min_height, pick.max_height) == (0, 0, 0)
    assert pick.buildable is True and pick.road is False
    assert pick.owner is not None


def test_tile_facts_stay_squirrel_booleans_with_integer_stub_predicates():
    """TerrainFactNorm keeps the wire shape when some native layer surfaces
    the predicates as the integers 0/1 instead of Squirrel booleans."""
    world = corrected_vm()
    set_global(world, "fact_ints = true;")
    first = terrain_drive(world, order("radius-00", None))
    assert first.status == "READY"
    reply = terrain_drive(world, order("tile-00", TERRAIN_TILES[0]))
    assert reply.status == "READY" and reply.tile == TERRAIN_TILES[0]
    # After normalization every fact is a bool on the wire and in the table.
    assert reply.buildable is True
    assert (reply.tree, reply.water, reply.coast) == (False, False, False)
    assert (reply.farm, reply.rock, reply.rough) == (False, False, False)
    assert reply.road is True  # 50095's road fact survives integer->bool
    types = fact_types(world)
    assert "buildable:bool" in types and "tree:bool" in types
    assert "road:bool" in types and "water_transport:bool" in types


def test_handler_measures_the_acceptance_pair_under_the_native_radius():
    replies = run_schedule(corrected_vm())
    control = replies[8]
    stop = replies[9]
    assert (control.tile, control.accept, control.radius) == (50351, 8, 8)
    assert (stop.tile, stop.accept, stop.radius) == (50862, 8, 8)


def test_handler_refuses_an_unpinned_tile_before_any_fact():
    world = corrected_vm()
    assert terrain_drive(world, order("radius-00", None)).status == "READY"
    # A scheduled tile exchange addressed to a tile outside TERRA_TILES
    # replies INVALID_LOCATION with its tile echo but no fact fields; a
    # hand-built body is the only way past the Python-side pin validator.
    probe = probe_request("tile", "tile-00", 45747)
    world.execute("::bridge.TerrainHandle(" + probe.to_bytes().decode() + ");")
    world.execute("::sniffer.last = last_reply_json();")
    raw = world.get_roottable()["sniffer"]["last"].encode()
    refuted = TerrainReadback.parse_for(probe_request("tile", "tile-00", 45747), raw)
    assert refuted.status == "INVALID_LOCATION"
    assert refuted.tile == 45747
    assert refuted.slope is None and refuted.buildable is None
    assert refuted.road is None and refuted.owner is None
    # The refusal is terminal for the scheduled exchange: the terrain stage
    # halts prefix-preservingly (the probed id is consumed, so the next
    # scheduled exchange carries the halt for the record).
    later = terrain_drive(world, order("tile-01", TERRAIN_TILES[1]))
    assert later.status == "OUT_OF_ORDER"
    assert later.tile == TERRAIN_TILES[1]
    assert later.slope is None and later.road is None


def test_handler_refuses_out_of_order_and_duplicate_terrain_ids():
    world = corrected_vm()
    stray = terrain_drive(world, order("tile-00", TERRAIN_TILES[0]))
    assert stray.status == "OUT_OF_ORDER"
    assert stray.tile == TERRAIN_TILES[0]
    assert stray.slope is None and stray.buildable is None
    # A fresh terrain session then runs cleanly; a duplicate id is dropped
    # silently and the stage is untouched.
    world = corrected_vm()
    first = terrain_drive(world, order("radius-00", None))
    assert first.status == "READY"
    dropped(world, order("radius-00", None))
    assert terrain_drive(world, order("tile-00", TERRAIN_TILES[0])).status == "READY"


def test_handler_refuses_drifted_pins_companies_and_paused_worlds():
    world = corrected_vm()
    assert terrain_drive(world, order("radius-00", None)).status == "READY"
    reply = terrain_drive(world, rerolled("tile-00", TERRAIN_TILES[0], delivery=50352))
    assert reply.status == "STALE_PIN"
    assert reply.slope is None and reply.tile == TERRAIN_TILES[0]
    # A paused world is refused before any observation field attaches.
    paused = _freight_build_vm(paused=True)
    paused.execute(TERRAIN_FACT_WORLD)
    paused.execute(PATCHED_SRC)
    paused.execute("::bridge <- D5FreightProof();")
    answer = terrain_drive(paused, order("radius-00", None))
    assert answer.status == "PAUSED"
    assert answer.slope is None and answer.accept is None
    # A company broadcast resolving elsewhere is refused INVALID_COMPANY
    # before any observation.
    foreign = (
        '{"protocol":7,"op":"radius","request_id":"radius-00","plan":"'
        + SEAL
        + '","company":1,"max_cost":0,"pickup":45748,"delivery":50351,"depot":45487,'
        '"tile":null}'
    )
    fresh = corrected_vm()
    fresh.execute(f"::bridge.TerrainHandle({foreign});")
    fresh.execute("::sniffer.last = last_reply_json();")
    assert "INVALID_COMPANY" in fresh.get_roottable()["sniffer"]["last"]


def test_handler_refuses_unsupported_native_acceptance():
    world = corrected_vm()
    set_global(world, "accept = 9;")
    for exchange, _op, tile in SCHEDULE[:8]:  # radius + tile-00..tile-06
        assert terrain_drive(world, order(exchange, tile)).status == "READY"
    beyond = terrain_drive(world, order("accept-00", TERRAIN_ACCEPT_CONTROL_TILE))
    assert beyond.status == "UNSUPPORTED_NATIVE_FACT"
    assert beyond.accept is None and beyond.radius is None
    assert beyond.tile == TERRAIN_ACCEPT_CONTROL_TILE


def test_terrain_stage_halts_prefix_preservingly_on_a_terminal_status():
    world = _freight_build_vm(paused=True)
    world.execute(TERRAIN_FACT_WORLD)
    world.execute(PATCHED_SRC)
    world.execute("::bridge <- D5FreightProof();")
    assert terrain_drive(world, order("radius-00", None)).status == "PAUSED"
    # Unpausing cannot retry the halted schedule: the later, now-correct
    # exchange is refused OUT_OF_ORDER for the record.
    set_global(world, "paused = false;")
    later = terrain_drive(world, order("tile-00", TERRAIN_TILES[0]))
    assert later.status == "OUT_OF_ORDER"
    assert later.slope is None and later.buildable is None


def test_terrain_dispatch_shares_the_shared_32_request_budget():
    """The terrain survey shares the dispatcher's one-shot 32-request cap
    with the freight and survey protocols: 10 scheduled exchanges plus
    foreign-id probes fill the budget; request 33 and any duplicate id are
    silently dropped (no reply, no schedule movement)."""
    world = corrected_vm()
    for exchange, _op, tile in SCHEDULE:
        assert terrain_drive(world, order(exchange, tile)).status == "READY"
    for index in range(22):
        probe = probe_request("radius", f"probe-{index:02d}", None)
        assert terrain_drive(world, probe).status == "OUT_OF_ORDER"
    assert len(world.get_roottable()["replies"]) == 10 + 22 == TERRAIN_REQUEST_BUDGET
    dropped(world, probe_request("radius", "probe-22", None))
    assert len(world.get_roottable()["replies"]) == TERRAIN_REQUEST_BUDGET
    dropped(world, probe_request("radius", "probe-00", None))
    assert len(world.get_roottable()["replies"]) == TERRAIN_REQUEST_BUDGET


def test_terrain_additivity_leaves_protocols_5_and_6_answering_ready():
    """Protocol isolation probes: the same bridge still answers the freight
    and acceptance-survey surfaces exactly as their suites model them (the
    full surfaces are covered by tests/test_corridor_freight.py and
    tests/test_corridor_accept_survey.py, both run as suites); this is the
    minimal VM probe that the terrain stubs added here disturb neither
    handler's stub behaviour)."""
    from app.simulation.openttd.corridor_accept_survey import (
        SurveyReadback,
        SurveyRequest,
    )
    from app.simulation.openttd.corridor_freight import FreightReadback

    world = corrected_vm()
    survey = SurveyRequest.model_validate(
        {
            "op": "radius",
            "request_id": "radius-00",
            "plan": SEAL,
            "company": 0,
            "max_cost": 0,
            "pickup": 45748,
            "delivery": 50351,
            "depot": 45487,
            "tile": None,
        }
    )
    world.execute("::bridge.Handle(" + survey.to_bytes().decode() + ");")
    world.execute("::sniffer.last = last_reply_json();")
    parsed = SurveyReadback.parse_for(survey, world.get_roottable()["sniffer"]["last"].encode())
    assert parsed.status == "READY" and parsed.radius == 8 and parsed.funds == FUNDS
    # Protocol 5: the freight site exchange answers READY on its own fresh
    # bridge (one plan identity per instance; the terrain stubs added here
    # inherit the parent GSTile members the freight path reads).
    freight_world = corrected_vm()
    commission = freight_site_request()
    freight_world.execute("::bridge.Handle(" + commission.to_bytes().decode() + ");")
    freight_world.execute("::sniffer.last = last_reply_json();")
    freight = FreightReadback.parse_for(
        commission, freight_world.get_roottable()["sniffer"]["last"].encode()
    )
    assert freight.status == "READY"


def test_wire_entry_point_dispatches_protocol_7_terrain_frames():
    """Regression pin for the review's material finding: the shipped
    ``Handle`` must route protocol-7 tables to ``TerrainHandle``; before the
    fix the branch was missing and every real terrain exchange timed out
    while the tests called ``TerrainHandle`` directly."""
    world = corrected_vm()
    req = order("radius-00", None)
    world.execute("::bridge.Handle(" + req.to_bytes().decode() + ");")
    world.execute("::sniffer.last = last_reply_json();")
    parsed = TerrainReadback.parse_for(req, world.get_roottable()["sniffer"]["last"].encode())
    assert parsed.status == "READY" and parsed.radius == 8 and parsed.funds == FUNDS
    assert parsed.plan == SEAL and parsed.cost == 0
