"""Schema-2 classification dispatch through the proven secure-transport seam.

Offline only: fully controlled in-memory peers; no OpenTTD launch, no
AdminPort connection and no authorization consumption is possible here. The
fake peer answers the deterministic classification plan over the same
ADMIN_GAMESCRIPT channel the secure session uses (plus the ordered barrier
pongs), proving that the transport keys one unique (request_id, region,
cursor) per page while rejecting replays, duplicate frames, garbage payloads
and barrier violations. Schema-1 facts dispatch is exercised on the same
connection as a regression.
"""

import asyncio
import hashlib
import json
import struct
from unittest.mock import AsyncMock, Mock

import pytest
from test_p08_controlled_road import world_for
from test_tile_classification_receipt import (
    CENSUS_REQUEST_ID,
    census_dict,
    exchanges_for,
)

from app.simulation.openttd.admin_protocol import ServerProtocol
from app.simulation.openttd.gamescript_transport import (
    ADMIN_GAMESCRIPT,
    SERVER_GAMESCRIPT,
    GameScriptSession,
    GameScriptTransport,
    MalformedResponse,
    TransportProtocolError,
    decode_gamescript,
    tile_region_selector,
)
from app.simulation.openttd.observation_protocol import BridgeProtocolError
from app.simulation.openttd.supplemental_planning_facts import SupplementalPlanningFacts
from app.simulation.openttd.tile_classification import (
    TileClassificationRequest,
    classification_plan,
)
from app.simulation.openttd.tile_facts import (
    Region,
    TileFactsExchange,
    TileFactsReceipt,
    TileFactsRequest,
    TileFactsResponse,
    TileFailure,
    TileQueryError,
)

BARRIER_TOKEN = 0x154
SUBSCRIPTION_TOKEN = 0x153


@pytest.fixture(scope="module")
def census():
    """The controlled 64x64 world projected into the retained census shape."""
    raw = census_dict(world_for(accepts=(1,)))
    facts = SupplementalPlanningFacts.model_validate_json(json.dumps(raw))
    digest = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()
    bands = {
        tuple(band)
        for band in (r.region for r in classification_plan(facts.region, CENSUS_REQUEST_ID))
    }
    assert len(bands) == 2
    return facts, digest, facts.source.map_width, facts.source.map_height


def used_key(request) -> str:
    """The transport's exact uniqueness key (kept in parity with _used_key)."""
    return "\0".join(
        (
            request.request_id,
            ",".join(map(str, tile_region_selector(request.region))),
            str(request.cursor),
        )
    )


def gs_frame(payload: bytes) -> bytes:
    """One SERVER_GAMESCRIPT wire frame carrying a null-terminated payload."""
    return struct.pack("<HB", len(payload) + 4, SERVER_GAMESCRIPT) + payload + b"\0"


def broken_frame(body: bytes) -> bytes:
    """A SERVER_GAMESCRIPT frame whose payload violates the string framing."""
    return struct.pack("<HB", len(body) + 3, SERVER_GAMESCRIPT) + body


def census_store(census):
    facts, digest, map_width, map_height = census
    requests, exchanges = exchanges_for(facts, map_width, map_height)
    store = dict(zip((used_key(r) for r in requests), (e.response_payload for e in exchanges)))
    return requests, exchanges, store


class ControlledPeer:
    """Answers classification pages and barrier pongs like the staged bridge."""

    def __init__(self, store: dict, defect=None, *, wrong_token: bool = False):
        self.store = dict(store)
        self.defect = defect
        self.wrong_token = wrong_token
        self.barrier_excess: bytes | None = None
        self.keys: list = []

    def write(self, reader, frame: bytes) -> None:
        length, kind = struct.unpack_from("<HB", frame)
        if kind == 7:  # AdminPing barrier: binary body, no terminator
            token = struct.unpack("<I", frame[3:length])[0]
            token ^= 1 if self.wrong_token else 0
            reader.feed_data(struct.pack("<HB", 7, 126) + struct.pack("<I", token))
            if token == BARRIER_TOKEN and self.barrier_excess is not None:
                reader.feed_data(self.barrier_excess)
                self.barrier_excess = None
            return
        if kind == 2:
            return  # UPDATE_FREQUENCY subscription packet: no reply by protocol
        if kind != ADMIN_GAMESCRIPT:
            return
        decoded = decode_gamescript(frame[3:])
        try:
            request = TileClassificationRequest.parse(decoded)
            key: object = used_key(request)
        except BridgeProtocolError:
            key = decoded  # schema-1 facts requests keep their payload identity
        self.keys.append(key)
        frames = self.defect(key) if self.defect else None
        if frames is None:
            frames = [gs_frame(self.store[key])]
        for one in frames:
            reader.feed_data(one)


def wire(peer: ControlledPeer) -> GameScriptTransport:
    reader = asyncio.StreamReader()
    writer = Mock(spec=asyncio.StreamWriter)
    writer.drain = AsyncMock()
    writer.wait_closed = AsyncMock()
    writer.is_closing.return_value = False
    writer.write.side_effect = lambda frame: peer.write(reader, frame)
    session = GameScriptSession(reader, writer)
    return GameScriptTransport(session, ServerProtocol(3, ((9, 64),)))


def run(coro):
    return asyncio.run(coro)


def page_once(transport, request):
    return transport.tile_classification_page(request, timeout=2, operation_budget=8)


def test_full_controlled_census_walk(census):
    requests, exchanges, store = census_store(census)
    peer = ControlledPeer(store)

    async def scenario():
        transport = wire(peer)
        walked = [await page_once(transport, r) for r in requests]
        return walked, transport

    walked, _transport = run(scenario())
    assert peer.keys == [used_key(r) for r in requests]
    assert len(set(peer.keys)) == len(peer.keys)
    for request, exchange, observed in zip(requests, exchanges, walked, strict=True):
        assert observed.request_payload == request.to_bytes()
        assert observed.response_payload == exchange.response_payload
        assert observed.receipt == exchange.receipt
    # First page carries the subscription (2 ops + its pong); later pages reuse it.
    assert [e.protocol_operations for e in walked] == [7] + [4] * 89


def test_replayed_stale_page_rejected(census):
    requests, exchanges, store = census_store(census)
    stale_key = used_key(requests[0])
    # The peer replies to page 1 with page 0's response: a stale replay.
    peer = ControlledPeer(
        store, defect=lambda key: [gs_frame(store[stale_key])] if key != stale_key else None
    )

    async def scenario():
        transport = wire(peer)
        await page_once(transport, requests[0])
        await page_once(transport, requests[1])

    with pytest.raises(TransportProtocolError) as failed:
        run(scenario())
    assert isinstance(failed.value.__cause__, TileQueryError)
    assert failed.value.__cause__.code is TileFailure.CURSOR_MISMATCH


def test_transport_unusable_after_failed_page(census):
    requests, exchanges, store = census_store(census)
    stale_key = used_key(requests[0])
    peer = ControlledPeer(
        store, defect=lambda key: [gs_frame(store[stale_key])] if key != stale_key else None
    )

    async def scenario():
        transport = wire(peer)
        await page_once(transport, requests[0])
        try:
            await page_once(transport, requests[1])
        except TransportProtocolError:
            pass
        await page_once(transport, requests[2])

    with pytest.raises(TransportProtocolError) as failed:
        run(scenario())
    assert "unavailable" in str(failed.value)


def test_duplicate_response_frame_rejected(census):
    requests, exchanges, store = census_store(census)
    key = used_key(requests[0])
    payload = store[key]
    peer = ControlledPeer(store, defect=lambda k: [gs_frame(payload), gs_frame(payload)])

    async def scenario():
        transport = wire(peer)
        await page_once(transport, requests[0])

    with pytest.raises(TransportProtocolError) as failed:
        run(scenario())
    assert "duplicate" in str(failed.value)


def test_garbage_wire_payload_converted_fail_closed(census):
    requests, exchanges, store = census_store(census)
    # Frame body without a null terminator breaks the GameScript string framing.
    peer = ControlledPeer(store, defect=lambda k: [broken_frame(b"zzz")])

    async def scenario():
        transport = wire(peer)
        await page_once(transport, requests[0])

    with pytest.raises(MalformedResponse):
        run(scenario())


def test_non_json_payload_rejected(census):
    requests, exchanges, store = census_store(census)
    peer = ControlledPeer(store, defect=lambda k: [gs_frame(b'{"broken": tru')])

    async def scenario():
        transport = wire(peer)
        await page_once(transport, requests[0])

    with pytest.raises(TransportProtocolError) as failed:
        run(scenario())
    assert isinstance(failed.value.__cause__, TileQueryError)
    assert failed.value.__cause__.code is TileFailure.MALFORMED_RESPONSE


def test_surplus_page_frame_after_pong_rejected(census):
    """A queued second response must die at the ordered completion barrier."""
    requests, exchanges, store = census_store(census)
    key = used_key(requests[0])
    # The peer serves the correct response, then rides the barrier pong of the
    # same first-page query with a replayed response frame.
    peer = ControlledPeer(store, defect=lambda k: [gs_frame(store[key])])
    peer.barrier_excess = gs_frame(store[key])

    async def scenario():
        transport = wire(peer)
        await page_once(transport, requests[0])

    with pytest.raises(TransportProtocolError) as failed:
        run(scenario())
    assert "duplicate/unrelated" in str(failed.value)


def test_wrong_barrier_token_rejected(census):
    requests, exchanges, store = census_store(census)
    peer = ControlledPeer(store, wrong_token=True)

    async def scenario():
        transport = wire(peer)
        await page_once(transport, requests[0])

    with pytest.raises(TransportProtocolError) as failed:
        run(scenario())
    assert "token" in str(failed.value)


def test_repeated_used_key_refuses_second_page(census):
    requests, exchanges, store = census_store(census)
    peer = ControlledPeer(store)

    async def scenario():
        transport = wire(peer)
        await page_once(transport, requests[0])
        await page_once(transport, requests[0])

    with pytest.raises(TransportProtocolError) as failed:
        run(scenario())
    assert "fresh request_id" in str(failed.value)


def test_schema1_facts_dispatch_unchanged_on_same_transport(census):
    """A v1 facts page rides the same transport after a schema-2 page."""
    requests, exchanges, store = census_store(census)
    region = Region(x=0, y=0, width=1, height=1)
    fact_request = TileFactsRequest("legacy-facts-1", region, 0)
    row = (0, 1, 13, 0, None, -1, 0, 0, 0, 0)
    fact_response = TileFactsResponse(
        "legacy-facts-1",
        region,
        0,
        64,
        64,
        712223,
        712223,
        (row,),
        None,
        False,
    )
    receipt = TileFactsReceipt.correlate(fact_request.to_bytes(), fact_response.to_bytes())
    assert TileFactsResponse.parse(fact_response.to_bytes()) == fact_response
    peer = ControlledPeer({**store, fact_request.to_bytes(): fact_response.to_bytes()})

    async def scenario():
        transport = wire(peer)
        await page_once(transport, requests[0])
        return await transport.tile_facts_page(fact_request, timeout=2)

    exchange = run(scenario())
    assert isinstance(exchange, TileFactsExchange)
    assert exchange.response_payload == fact_response.to_bytes()
    assert exchange.receipt == receipt
