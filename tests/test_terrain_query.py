"""Controlled vertical handler/wire/collector/evidence tests, with no native client."""

import asyncio
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from squirrel import SQVM
from test_supplemental_planning_contracts import fact_dict, world_for

from app.simulation.openttd.supplemental_planning_facts import FactSource, Region
from app.simulation.openttd.terrain_bridge import terrain_bridge_source
from app.simulation.openttd.terrain_collection import TerrainBudget, TerrainCollector
from app.simulation.openttd.tile_facts import (
    TileFactsExchange,
    TileFactsReceipt,
    TileFactsRequest,
    TileFactsResponse,
    TileQueryError,
)
from app.simulation.openttd.tile_facts_evidence import parse_tile_facts_evidence

PREFIX = "dbg: [script:4] [18] [I] "


def vm_source():
    return (
        Path("tests/fixtures/gamescript_api_15.nut").read_text()
        + Path("tests/fixtures/tile_facts_api_15.nut").read_text()
        + terrain_bridge_source()
    )


def wire_value(v):
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if hasattr(v, "keys"):
        return {str(k): wire_value(v[k]) for k in v.keys()}
    return [wire_value(x) for x in v]


def gs_request(q):
    r = q.region
    return (
        '{protocol=1,type="tile_facts_page",request_id="'
        + q.request_id
        + f'",region=[{r.x},{r.y},{r.width},{r.height}],cursor={q.cursor}'
        + "}"
    )


@pytest.mark.parametrize(
    "r",
    [
        Region(x=0, y=0, width=1, height=1),
        Region(x=4094, y=4094, width=1, height=1),
        Region(x=100, y=100, width=16, height=16),
    ],
)
def test_actual_handler_records(r):
    vm = SQVM()
    vm.execute(vm_source())
    q = TileFactsRequest("tile", r, 0)
    vm.execute("::b <- NoMutationBridge(); b.Handle(" + gs_request(q) + ");")
    root = vm.get_roottable()
    payload = json.dumps(
        wire_value(root["replies"][0]), sort_keys=True, separators=(",", ":")
    ).encode()
    ex = TileFactsExchange(q.to_bytes(), payload, TileFactsReceipt.correlate(q.to_bytes(), payload))
    assert len(ex.response.tiles) == min(5, r.width * r.height)
    assert root["calls"] <= len(ex.response.tiles) * 44 + 6
    markers = [str(m) for m in root["markers"]]
    assert (
        markers[1]
        == "TILE_FACTS_READ request_id=tile response_json=" + ex.response.to_bytes().decode()
    )


@pytest.mark.parametrize(
    "change,expected",
    [
        ("::airport=true;", 1025),
        ("::house=true;", 2049),
        ("::station=true;", 4097),
        ("::road=true;", 129),
    ],
)
def test_occupancy_and_directed_connections(change, expected):
    vm = SQVM()
    vm.execute(vm_source())
    vm.execute(change)
    q = TileFactsRequest("tile", Region(x=2, y=2, width=2, height=1), 0)
    vm.execute("::b <- NoMutationBridge(); b.Handle(" + gs_request(q) + ");")
    r = TileFactsResponse.parse(
        json.dumps(
            wire_value(vm.get_roottable()["replies"][0]), sort_keys=True, separators=(",", ":")
        ).encode()
    )
    assert r.rows[0][3] == expected
    if "road" in change:
        assert r.rows[0][7] == 2 and r.rows[0][8] == 0
        assert r.rows[1][7] == 0 and r.rows[1][8] == 8
    if "house" in change or "station" in change:
        assert not r.tiles[0].buildable


@pytest.mark.parametrize(
    "change,code",
    [
        ("::void_tile=8194;", "INVALID_TILE"),
        ("::slope=65535;", "UNSUPPORTED_NATIVE_FACT"),
        ("::elevation=-1;", "UNSUPPORTED_NATIVE_FACT"),
        ("::owner=255;", "UNSUPPORTED_NATIVE_FACT"),
        ("::setter_refuses=true;", "UNSUPPORTED_ROAD_TYPE"),
        ("::available=false;", "UNSUPPORTED_ROAD_TYPE"),
    ],
)
def test_handler_rejects_unknown_without_false_defaults(change, code):
    vm = SQVM()
    vm.execute(vm_source())
    vm.execute(change)
    q = TileFactsRequest("tile", Region(x=2, y=2, width=1, height=1), 0)
    vm.execute("::b <- NoMutationBridge(); b.Handle(" + gs_request(q) + ");")
    assert str(vm.get_roottable()["replies"][0]["error_code"]) == code


def test_event_loop_post_response_liveness():
    vm = SQVM()
    vm.execute(vm_source())
    q = TileFactsRequest("alive", Region(x=2, y=2, width=1, height=1), 0)
    vm.execute(
        "::events.append(ControlledAdminEvent("
        + gs_request(q)
        + ')); ::b <- NoMutationBridge(); try{b.Start();}catch(e){if(e!="CONTROLLED_STOP")throw e;}'
    )
    root = vm.get_roottable()
    raw = "".join(PREFIX + str(m) + "\n" for m in root["markers"]).encode()
    payload = json.dumps(
        wire_value(root["replies"][0]), sort_keys=True, separators=(",", ":")
    ).encode()
    ex = TileFactsExchange(q.to_bytes(), payload, TileFactsReceipt.correlate(q.to_bytes(), payload))
    parse_tile_facts_evidence(raw, "alive").require_complete(ex)
    assert [int(x) for x in root["marker_ticks"]][-1] == 1


def test_exact_tagged_vm(tmp_path):
    exe = os.environ.get("SQUIRREL_15_3_PROBE")
    if not exe:
        pytest.skip("tagged offline VM not configured")
    path = tmp_path / "terrain.nut"
    q = TileFactsRequest("tagged", Region(x=2, y=2, width=16, height=16), 0)
    path.write_text(
        vm_source()
        + "\nlocal b=NoMutationBridge(); b.Handle("
        + gs_request(q)
        + '); b.Handle({protocol=1,type="ping",request_id="old"});'
        + ' if(::replies.len()!=2)throw "dispatch";'
    )
    result = subprocess.run([exe, str(path)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


class FakeClient:
    def __init__(self, world, defect=None):
        self.context = world.context
        self.session = object()
        self.world = world
        self.defect = defect
        self.requests = []
        self.logs = {}
        self.operation_count = 4
        from app.simulation.openttd.terrain_accounting import TerrainFrameBudget

        self.frame_budget = TerrainFrameBudget()
        self.frame_budget.consume("establishment", 2)
        self.frame_budget.enter("setup")
        self.frame_budget.consume("setup", 3)

    async def tile_facts_page(self, q, **kwargs):
        self.requests.append(q)
        r = q.region
        count = min(5, r.width * r.height - q.cursor)
        rows = []
        width = self.context.world.map_width
        for ordinal in range(q.cursor, q.cursor + count):
            x = r.x + ordinal % r.width
            y = r.y + ordinal // r.width
            assessed = 0
            for bit, (dx, dy) in enumerate(((0, -1), (1, 0), (0, 1), (-1, 0))):
                if r.x <= x + dx < r.x + r.width and r.y <= y + dy < r.y + r.height:
                    assessed |= 1 << bit
            rows.append((y * width + x, 0, 0, 1, None, -1, 0, 0, 0, assessed))
        date = self.world.production.qualification.current_month.start_date
        response = TileFactsResponse(
            q.request_id,
            r,
            q.cursor,
            width,
            self.context.world.map_height,
            date,
            date,
            tuple(rows),
            q.cursor + count if q.cursor + count < r.width * r.height else None,
            q.cursor + count < r.width * r.height,
        )
        d = json.loads(response.to_bytes())
        if self.defect == "drift" and "-s2-" in q.request_id:
            d["tiles"][0][1] = 1
        if self.defect == "duplicate":
            d["tiles"][-1] = d["tiles"][0]
        if self.defect == "missing":
            d["tiles"].pop()
        if self.defect == "order":
            d["tiles"].reverse()
        if self.defect == "cursor":
            d["cursor"] = 5
        if self.defect == "id":
            d["request_id"] = "other"
        if self.defect == "month":
            d["date_after"] = self.world.production.qualification.current_month.end_date
        if self.defect == "runtime":
            self.context = replace(
                self.context,
                world=replace(
                    self.context.world,
                    runtime_identity=replace(self.context.world.runtime_identity, sha256="b" * 64),
                ),
            )
        if self.defect == "bridge":
            self.context = replace(
                self.context, bridge=replace(self.context.bridge, sha256="b" * 64)
            )
        if self.defect == "connection":
            self.session = object()
        payload = json.dumps(d, sort_keys=True, separators=(",", ":")).encode()
        ex = TileFactsExchange(
            q.to_bytes(),
            payload,
            TileFactsReceipt.correlate(q.to_bytes(), payload),
            protocol_operations=self.operation_count,
        )
        phase = "sweep2" if "-s2-" in q.request_id else "sweep1"
        self.frame_budget.consume(phase, self.operation_count)
        self.logs[q.request_id] = (
            "BRIDGE_REQUEST_RECEIVED request_id="
            + q.request_id
            + " type=tile_facts_page protocol=1",
            "TILE_FACTS_READ request_id=" + q.request_id + " response_json=" + payload.decode(),
            "BRIDGE_RESPONSE_SENT request_id="
            + q.request_id
            + " type=tile_facts_page_result status=ok protocol=1",
            "BRIDGE_POST_RESPONSE_ALIVE request_id=" + q.request_id,
        )
        return ex

    async def evidence(self, q, ex):
        lines = self.logs[q.request_id]
        if self.defect == "alive":
            lines = lines[:-1]
        if self.defect == "digest":
            lines = list(lines)
            lines[1] = lines[1].replace("response_json=", "response_json= ")
        return parse_tile_facts_evidence(
            "".join(PREFIX + s + "\n" for s in lines).encode(), q.request_id
        )


def owner(n=6, budget=TerrainBudget(), defect=None):
    world = world_for()
    source = FactSource.model_validate_json(json.dumps(fact_dict(world)["source"]))
    region = Region(
        x=0,
        y=0,
        width=15 if n == 255 else 16 if n == 256 else n,
        height=17 if n == 255 else 16 if n == 256 else 1,
    )
    return TerrainCollector(world, source, region, budget=budget), FakeClient(world, defect)


@pytest.mark.parametrize("n,requests", [(1, 2), (5, 2), (6, 4), (255, 102), (256, 104)])
def test_complete_two_sweeps(n, requests):
    c, client = owner(n)
    result = asyncio.run(c.collect(client, client.evidence))
    assert len(result.tiles) == n and len(client.requests) == requests
    assert (
        result.world is c.world
        and result.source.production_digest == c.world.production.production_digest
    )
    assert result.trust.value == "CONTROLLED_FIXTURE"
    assert c.getter_calls == 2 * n * 44 + requests * 6
    assert c.operations == requests * 4
    assert len(result.semantic_digest) == 64
    with pytest.raises(TileQueryError):
        asyncio.run(c.collect(client, client.evidence))
    with pytest.raises(TileQueryError):
        replace(result, trust="REAL_RUNTIME_CORRESPONDENCE_PROVEN")


@pytest.mark.parametrize(
    "defect",
    [
        "drift",
        "duplicate",
        "missing",
        "order",
        "cursor",
        "id",
        "month",
        "runtime",
        "bridge",
        "connection",
        "alive",
        "digest",
    ],
)
def test_failed_collection_never_publishes(defect):
    c, client = owner(defect=defect)
    with pytest.raises(TileQueryError):
        asyncio.run(c.collect(client, client.evidence))
    assert c.result is None and c.failure and c.started
    assert len(client.requests) <= 4
    with pytest.raises(TileQueryError):
        asyncio.run(c.collect(client, client.evidence))


@pytest.mark.parametrize(
    "budget",
    [
        TerrainBudget(max_requests=1),
        TerrainBudget(max_response_bytes=507),
        TerrainBudget(max_operations=3),
        TerrainBudget(max_getter_calls=49),
    ],
)
def test_phase_budget_fails_before_overlimit_send(budget):
    c, client = owner(1, budget)
    with pytest.raises(TileQueryError):
        asyncio.run(c.collect(client, client.evidence))
    assert c.requests <= budget.max_requests


def test_deterministic_replay():
    c, a = owner()
    d, b = owner()
    x = asyncio.run(c.collect(a, a.evidence))
    y = asyncio.run(d.collect(b, b.evidence))
    assert x.semantic_digest == y.semantic_digest
    assert [q.to_bytes() for q in a.requests] == [q.to_bytes() for q in b.requests]


def test_shared_frame_accounting_exact_ceiling_and_no_reset():
    from app.simulation.openttd.proof.structural_contract import StructuralFrameBudgetExceeded
    from app.simulation.openttd.terrain_accounting import TerrainFrameBudget

    b = TerrainFrameBudget()
    b.consume("establishment", 2)
    b.enter("setup")
    b.consume("setup", 3)
    b.enter("sweep1")
    b.consume("sweep1", 416)
    b.enter("sweep2")
    b.consume("sweep2", 416)
    b.enter("cleanup")
    b.consume("cleanup")
    assert b.total_frames == 838 and b.query_operations == 832
    with pytest.raises(ValueError):
        b.enter("establishment")
    with pytest.raises(StructuralFrameBudgetExceeded):
        b.consume("sweep2")


def test_exact_query_and_getter_budget_at_256_tiles():
    c, client = owner(256)
    client.operation_count = 8
    r = asyncio.run(c.collect(client, client.evidence))
    assert c.requests == 104 and c.operations == 832 and c.getter_calls == 23152
    assert len(r.sweeps[0]) == 52 and len(r.sweeps[1]) == 52
    assert c.response_bytes <= 52832
    assert all(p["operations"] == 416 and p["requests"] == 52 for p in c.phase_counts)


def test_real_transport_branch_with_supplied_stream_only():
    from unittest.mock import AsyncMock, Mock

    from app.simulation.openttd.admin_protocol import ServerProtocol, encode_admin_frame
    from app.simulation.openttd.gamescript_transport import (
        GameScriptSession,
        GameScriptTransport,
        decode_gamescript,
    )

    world = world_for()

    async def run():
        fake = FakeClient(world)
        reader = asyncio.StreamReader()
        writer = Mock(spec=asyncio.StreamWriter)
        writer.drain = AsyncMock()
        writer.wait_closed = AsyncMock()
        writer.is_closing.return_value = False
        q = TileFactsRequest("network", Region(x=0, y=0, width=1, height=1), 0)
        ex = await fake.tile_facts_page(q)
        packets = []

        def write(frame):
            packets.append(frame)
            if frame[2] == 7:
                reader.feed_data(encode_admin_frame(126, frame[3:]))
            if frame[2] == 6:
                assert TileFactsRequest.parse(decode_gamescript(frame[3:])) == q
                reader.feed_data(encode_admin_frame(124, ex.response_payload + b"\0"))

        writer.write.side_effect = write
        session = GameScriptSession(reader, writer)
        client = GameScriptTransport(session, ServerProtocol(3, ((9, 64),)))
        await client.subscribe()
        result = await client.tile_facts_page(q, operation_budget=8)
        result.validate()
        assert result.protocol_operations == 4 and len(packets) == 4
        assert sum(p[2] == 6 for p in packets) == 1
        with pytest.raises(ValueError):
            await client.tile_facts_page(q)
        await session.close()

    asyncio.run(run())


def test_pure_import_boundary():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import app.simulation.openttd.tile_facts; "
            "import app.simulation.openttd.tile_facts_evidence; "
            "import app.simulation.openttd.terrain_collection; "
            "assert not any(m in sys.modules for m in ['app.simulation.openttd.secure_admin',"
            "'app.simulation.openttd.gamescript_transport','app.planning.p08_road',"
            "'app.planning.optimizer','ortools','app.simulation.openttd.runtime'])",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_supplemental_contract_integration_requires_complete_independent_bundle():
    from app.simulation.openttd.supplemental_planning_facts import SupplementalPlanningFacts

    c, client = owner(1)
    r = asyncio.run(c.collect(client, client.evidence))
    d = fact_dict(c.world)
    d.update(
        region=r.region.model_dump(mode="json"),
        tiles=[t.model_dump(mode="json") for t in r.tiles],
        coverage_scopes=[],
        coverage=[],
        capture_economy_date_before=r.capture_economy_date_before,
        capture_economy_date_after=r.capture_economy_date_after,
    )
    facts = SupplementalPlanningFacts.model_validate_json(json.dumps(d))
    r.require_supplemental(facts)
    with pytest.raises(TileQueryError):
        r.require_supplemental(facts.model_copy(update={"tiles": ()}))


@pytest.mark.parametrize("mutation", ["read", "sent", "alive", "duplicate", "unterminated"])
def test_independent_evidence_cannot_be_replaced_by_receipt(mutation):
    c, client = owner(1)
    q = TileFactsRequest("evidence", c.region, 0)
    ex = asyncio.run(client.tile_facts_page(q))
    lines = list(client.logs[q.request_id])
    if mutation in ("read", "sent", "alive"):
        lines.pop({"read": 1, "sent": 2, "alive": 3}[mutation])
    if mutation == "duplicate":
        lines.append(lines[-1])
    raw = "".join(PREFIX + s + "\n" for s in lines).encode()
    if mutation == "unterminated":
        raw = raw[:-1]
    with pytest.raises(TileQueryError):
        parse_tile_facts_evidence(raw, q.request_id).require_complete(ex)


@pytest.mark.parametrize(
    "variable,value", [("owner", 14), ("industry", 63999), ("elevation", 255), ("slope", 31)]
)
def test_tagged_serializer_and_value_domains(tmp_path, variable, value):
    exe = os.environ.get("TILE_FACTS_SERIALIZER_PROBE")
    if not exe:
        pytest.skip("tagged serializer VM not configured")
    q = TileFactsRequest("x" * 64, Region(x=4000, y=4000, width=15, height=17), 250)
    script = (
        vm_source() + f"\n::{variable}={value}; ::road=true; ::airport=true; ::house=true; "
        "::station=true; ::elevation=255; ::slope=31; ::industry=63999;"
    )
    script += (
        " local b=NoMutationBridge(); b.Handle("
        + gs_request(q)
        + '); if(::replies.len()!=1)throw "missing";'
    )
    path = tmp_path / "serializer.nut"
    path.write_text(script)
    result = subprocess.run([exe, str(path)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    line = next(s[5:] for s in result.stdout.splitlines() if s.startswith("JSON "))
    assert len(line.encode()) <= 508
    r = TileFactsResponse.parse(line.encode())
    assert line.encode() == r.to_bytes()
    ops = int(result.stdout.splitlines()[0].split("=")[1])
    assert ops < 10000


def test_actual_tagged_serializer_exact_maximum_vector(tmp_path):
    exe = os.environ.get("TILE_FACTS_SERIALIZER_PROBE")
    if not exe:
        pytest.skip("tagged serializer VM not configured")
    d = json.loads(Path("tests/fixtures/p08_terrain_road_design.json").read_text())

    def squirrel(value):
        if value is None:
            return "null"
        if value is True:
            return "true"
        if value is False:
            return "false"
        if isinstance(value, str):
            return json.dumps(value)
        if isinstance(value, list):
            return "[" + ",".join(squirrel(x) for x in value) + "]"
        if isinstance(value, dict):
            return "{" + ",".join(k + "=" + squirrel(v) for k, v in value.items()) + "}"
        return str(value)

    vector = d["maximum_width_response"]
    path = tmp_path / "width.nut"
    for count, expected in [(5, 508), (6, 551)]:
        value = dict(vector)
        value["tiles"] = [vector["tiles"][0]] * count
        path.write_text("::replies <- [" + squirrel(value) + "];")
        result = subprocess.run([exe, str(path)], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
        payload = next(s[5:] for s in result.stdout.splitlines() if s.startswith("JSON ")).encode()
        assert len(payload) == expected
        assert payload == json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def test_accounting_observer_mismatch_rejects_receipt():
    c, client = owner(1)
    original = client.tile_facts_page

    async def query(q, **kwargs):
        ex = await original(q, **kwargs)
        # Retain observed extra frame: receipt cannot erase it.
        client.frame_budget.consume("sweep1")
        return ex

    client.tile_facts_page = query
    with pytest.raises(TileQueryError):
        asyncio.run(c.collect(client, client.evidence))
    assert c.result is None and client.frame_budget.query_operations == 5
