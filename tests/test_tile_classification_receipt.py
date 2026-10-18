"""Tile Classification V2 receipt, correlation and census binding tests.

Offline only: no OpenTTD launch, no AdminPort connection, no authorization
consumption. Every classification observation below is synthetic and derived
exactly from the retained TileFact projection inside each test; nothing here
claims a native measurement. The receipt layer is additive on schema 2; the
schema-1 wire contracts are only exercised as regression evidence.
"""

import hashlib
import json

import pytest
from test_p08_bounded_terrain import facts_at, retiled
from test_p08_controlled_road import world_for

from app.simulation.openttd.observation_protocol import MalformedMessage
from app.simulation.openttd.supplemental_planning_facts import (
    RandomCaptureRegion,
    Region,
    SupplementalPlanningFacts,
)
from app.simulation.openttd.tile_classification import (
    CLASSIFICATION_FLAG_NAMES,
    CLASSIFICATION_PAGE_LIMIT,
    CLASSIFICATION_SCHEMA_VERSION,
    CLASSIFICATION_TOTAL_RESPONSE_BYTES_LIMIT,
    TileClassificationExchange,
    TileClassificationReceipt,
    TileClassificationRequest,
    TileClassificationResponse,
    TileClassificationSweep,
    classification_plan,
    projection_disagrees,
)
from app.simulation.openttd.tile_facts import (
    MAX_RESPONSE_BYTES,
    PAGE_SIZE,
    TileFactsReceipt,
    TileFactsRequest,
    TileFactsResponse,
    TileFailure,
    TileQueryError,
)

CENSUS_X, CENSUS_Y, CENSUS_W, CENSUS_H = 8, 20, 45, 10
CENSUS_REQUEST_ID = "seed17-classification-census"
SCOPE = RandomCaptureRegion(
    x=CENSUS_X,
    y=CENSUS_Y,
    profile="random-rectangle-512-v1",
    width=CENSUS_W,
    height=CENSUS_H,
)
BAND_HEIGHT = 5
BAND = Region(x=CENSUS_X, y=CENSUS_Y, width=CENSUS_W, height=BAND_HEIGHT)
BIT = {name: 1 << i for i, name in enumerate(CLASSIFICATION_FLAG_NAMES)}
OBSERVED_DAYS = 712223


def flags15_from_fact(tile):
    """Schema-2 replay of the v1 TileFact projection (house/station stay 0)."""
    flags = 0
    if tile.buildable:
        flags |= BIT["buildable"]
    for name in ("water", "coast", "tree", "farm", "rock", "rough"):
        if getattr(tile, name):
            flags |= BIT[name]
    for name, attr in (
        ("road_tile", "road"),
        ("rail", "rail"),
        ("water_transport", "water_transport"),
        ("airport", "air_transport"),
    ):
        if getattr(tile, attr):
            flags |= BIT[name]
    return flags


def census_dict(world):
    """450-tile census region on the controlled 64x64 map with ground variety."""
    d = facts_at(world, CENSUS_X, CENSUS_Y, CENSUS_W, CENSUS_H)
    d["region"] = {
        "x": CENSUS_X,
        "y": CENSUS_Y,
        "profile": "random-rectangle-512-v1",
        "width": CENSUS_W,
        "height": CENSUS_H,
    }
    retiled(
        d,
        [
            (9, 21, {"tree": True, "buildable": False}),
            (10, 21, {"water": True, "buildable": False}),
            (11, 21, {"rail": True, "buildable": False}),
            (12, 21, {"road": True}),
            (13, 21, {"industry_id": 5}),
            (14, 21, {"air_transport": True, "buildable": False}),
            (10, 22, {"farm": True}),
            (11, 22, {"rough": True}),
            (12, 22, {"rock": True}),
            (13, 22, {"coast": True, "buildable": False}),
        ],
    )
    return d


def retained_welcome(map_width, map_height):
    """Synthetic observed-world identity for the controlled census."""
    return {
        "seed": 17,
        "width": map_width,
        "height": map_height,
        "landscape": 0,
        "revision": "15.3",
        "start_day": OBSERVED_DAYS,
    }


@pytest.fixture(scope="module")
def world():
    return world_for(accepts=(1,))


@pytest.fixture(scope="module")
def census(world):
    raw = census_dict(world)
    facts = SupplementalPlanningFacts.model_validate_json(json.dumps(raw))
    digest = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()
    assert facts.region == SCOPE
    return facts, digest, facts.source.map_width, facts.source.map_height


def response_row(facts, tile, patches):
    """One schema-2 row replaying exactly one retained TileFact observation."""
    fact = next(t for t in facts.tiles if t.tile_id == tile)
    patch = patches.get(tile, {})
    flags = patch.get("flags", flags15_from_fact(fact))
    industry = patch.get("industry", fact.industry_id)
    elevation = patch.get("elevation", fact.min_height)
    slope = patch.get("slope", fact.slope)
    return (tile, elevation, slope, flags, industry, 0)


def exchanges_for(census_facts, map_width, map_height, patches=None, request_id=CENSUS_REQUEST_ID):
    """Deterministic page set: one exchange per planned request, in plan order."""
    patches = patches or {}
    requests = classification_plan(census_facts.region, request_id)
    out = []
    for request in requests:
        band = request.region
        count = min(PAGE_SIZE, band.width * band.height - request.cursor)
        rows = tuple(
            response_row(
                census_facts,
                (band.y + (request.cursor + offset) // band.width) * map_width
                + band.x
                + (request.cursor + offset) % band.width,
                patches,
            )
            for offset in range(count)
        )
        more = request.cursor + count < band.width * band.height
        response = TileClassificationResponse(
            request_id=request_id,
            region=band,
            cursor=request.cursor,
            schema=CLASSIFICATION_SCHEMA_VERSION,
            map_width=map_width,
            map_height=map_height,
            date_before=OBSERVED_DAYS,
            date_after=OBSERVED_DAYS,
            rows=rows,
            next_cursor=request.cursor + count if more else None,
            has_more=more,
        )
        payload = response.to_bytes()
        receipt = TileClassificationReceipt.correlate(request.to_bytes(), payload)
        out.append(TileClassificationExchange(request.to_bytes(), payload, receipt))
    return tuple(requests), tuple(out)


def bound_sweep(census, patches=None, observed_welcome=None):
    facts, digest, map_width, map_height = census
    welcome = retained_welcome(map_width, map_height)
    requests, exchanges = exchanges_for(facts, map_width, map_height, patches)
    return TileClassificationSweep.record(
        requests,
        exchanges,
        retained_facts=facts,
        retained_facts_digest=digest,
        retained_welcome=welcome,
        observed_welcome=observed_welcome if observed_welcome is not None else dict(welcome),
    )


def test_receipt_correlate_roundtrip(census):
    facts, _, map_width, map_height = census
    requests, exchanges = exchanges_for(facts, map_width, map_height)
    receipt = TileClassificationReceipt.correlate(
        exchanges[0].request_payload, exchanges[0].response_payload
    )
    assert receipt.request_id == CENSUS_REQUEST_ID
    assert receipt.schema == CLASSIFICATION_SCHEMA_VERSION
    assert receipt.request_payload_sha256 == hashlib.sha256(requests[0].to_bytes()).hexdigest()
    assert (
        receipt.response_payload_sha256 == hashlib.sha256(exchanges[0].response_payload).hexdigest()
    )
    assert exchanges[0].receipt == receipt


def test_sweep_refuses_reencoded_request_bytes(census):
    """Exchanges must carry the exact pinned plan bytes, not an equal twin."""
    facts, digest, map_width, map_height = census
    requests, exchanges = exchanges_for(facts, map_width, map_height)
    raw = json.loads(exchanges[0].request_payload)
    # A legal but non-canonical re-encoding of the same request object.
    reencoded = json.dumps(raw, separators=(", ", ": "))
    # A fresh receipt derived from the re-encoded bytes: correlation itself
    # passes, so the refusal must come from the pinned-plan byte equality.
    receipt = TileClassificationReceipt.correlate(reencoded.encode(), exchanges[0].response_payload)
    tampered = TileClassificationExchange(
        reencoded.encode(), exchanges[0].response_payload, receipt
    )
    record = TileClassificationSweep.record
    welcome = retained_welcome(map_width, map_height)
    with pytest.raises(TileQueryError) as reencoded_bytes:
        record(
            requests,
            (tampered, *exchanges[1:]),
            retained_facts=facts,
            retained_facts_digest=digest,
            retained_welcome=welcome,
            observed_welcome=welcome,
        )
    assert reencoded_bytes.value.code is TileFailure.MALFORMED_RESPONSE


def test_receipt_identity_read_precedes_native_error(census):
    facts, _, map_width, map_height = census
    requests, exchanges = exchanges_for(facts, map_width, map_height)
    raw = json.loads(exchanges[0].response_payload)
    raw["schema"] = 7
    with pytest.raises(TileQueryError) as unsupported:
        TileClassificationReceipt.correlate(requests[0].to_bytes(), json.dumps(raw).encode())
    assert unsupported.value.code is TileFailure.UNSUPPORTED_CLASSIFICATION_SCHEMA
    wrong = dict(raw, request_id="other")
    with pytest.raises(TileQueryError) as mismatch:
        TileClassificationReceipt.correlate(requests[0].to_bytes(), json.dumps(wrong).encode())
    # Request identity is read before any bounded native error propagates,
    # so the wrong recipient wins over the rejected schema version.
    assert mismatch.value.code is TileFailure.REQUEST_ID_MISMATCH


def test_receipt_rejects_page_correspondence_drift(census):
    facts, _, map_width, map_height = census
    requests, exchanges = exchanges_for(facts, map_width, map_height)
    raw = json.loads(exchanges[3].response_payload)
    raw["cursor"] = raw["cursor"] + 5
    with pytest.raises(TileQueryError) as cursor:
        TileClassificationReceipt.correlate(requests[3].to_bytes(), json.dumps(raw).encode())
    assert cursor.value.code is TileFailure.CURSOR_MISMATCH
    raw = json.loads(exchanges[3].response_payload)
    raw["region"] = [raw["region"][0], raw["region"][1], raw["region"][2] + 5, raw["region"][3]]
    with pytest.raises(TileQueryError) as region:
        TileClassificationReceipt.correlate(requests[3].to_bytes(), json.dumps(raw).encode())
    assert region.value.code is TileFailure.CURSOR_MISMATCH
    raw = json.loads(exchanges[3].response_payload)
    raw.pop("region")
    with pytest.raises(MalformedMessage):
        # Mirror of the v1 receipt convention: a torn envelope is a generic
        # protocol-layer failure after the identity read, not a TileFailure.
        TileClassificationReceipt.correlate(requests[3].to_bytes(), json.dumps(raw).encode())


def test_exchange_fail_closed(census):
    facts, _, map_width, map_height = census
    _, exchanges = exchanges_for(facts, map_width, map_height)
    exchange = exchanges[0]
    exchange.validate()
    forged = TileClassificationExchange(
        exchange.request_payload,
        exchange.response_payload,
        TileClassificationReceipt(
            exchange.receipt.request_id,
            exchange.receipt.schema,
            exchange.receipt.request_payload_sha256,
            "0" * 64,
        ),
    )
    with pytest.raises(TileQueryError) as digest:
        forged.validate()
    assert digest.value.code is TileFailure.ACCOUNTING_LIMIT_EXCEEDED
    retried = TileClassificationExchange(
        exchange.request_payload, exchange.response_payload, exchange.receipt, retries=1
    )
    with pytest.raises(TileQueryError) as retries:
        retried.validate()
    assert retries.value.code is TileFailure.ACCOUNTING_LIMIT_EXCEEDED


def test_response_budget_enforced(census):
    facts, _, map_width, map_height = census
    requests, _ = exchanges_for(facts, map_width, map_height)
    padded = b'{"request_id":"' + CENSUS_REQUEST_ID.encode() + b'"}' + b" " * MAX_RESPONSE_BYTES
    assert len(padded) > MAX_RESPONSE_BYTES
    with pytest.raises(TileQueryError) as limited:
        TileClassificationReceipt.correlate(requests[0].to_bytes(), padded)
    assert limited.value.code is TileFailure.RESPONSE_LIMIT_EXCEEDED


def test_classification_plan_shapes_and_budgets(census):
    plan = classification_plan(SCOPE, CENSUS_REQUEST_ID)
    assert len(plan) == 90
    assert plan[0].region == BAND
    assert [request.cursor for request in plan[:45]] == [
        ordinal * PAGE_SIZE for ordinal in range(45)
    ]
    assert plan[45].region == Region(
        x=CENSUS_X, y=CENSUS_Y + BAND_HEIGHT, width=CENSUS_W, height=BAND_HEIGHT
    )
    assert plan[45].region.width * plan[45].region.height == 225
    # A census shape whose bounded plan would need more than
    # CLASSIFICATION_PAGE_LIMIT requests is refused instead of over-paging.
    wide = RandomCaptureRegion(x=0, y=0, profile="random-rectangle-512-v1", width=64, height=8)
    with pytest.raises(TileQueryError) as budget:
        classification_plan(wide, CENSUS_REQUEST_ID)
    assert budget.value.code is TileFailure.ACCOUNTING_LIMIT_EXCEEDED
    assert (
        CLASSIFICATION_PAGE_LIMIT * MAX_RESPONSE_BYTES == CLASSIFICATION_TOTAL_RESPONSE_BYTES_LIMIT
    )


def test_sweep_binds_complete_census(census):
    sweep = bound_sweep(census)
    facts, digest, _, _ = census
    assert sweep.bound is True
    assert sweep.pages == 90
    assert len(sweep.facts) == facts.region.width * facts.region.height
    assert sweep.region == facts.region
    assert sweep.retained_facts_digest == digest
    assert len(sweep.receipts) == 90
    assert all(receipt.request_id == CENSUS_REQUEST_ID for receipt in sweep.receipts)
    expected = {}
    for fact in sweep.facts:
        expected[fact.tile_class.value] = expected.get(fact.tile_class.value, 0) + 1
    assert sweep.class_counts == expected
    assert sweep.unknown_tiles == ()
    assert set(sweep.tile_classes) == {t.tile_id for t in facts.tiles}
    assert set(sweep.tile_flags) == set(sweep.tile_classes)
    index_classes, index_flags = sweep.require_bound()
    assert dict(index_classes) == sweep.tile_classes
    assert dict(index_flags) == sweep.tile_flags
    summary = json.loads(sweep.completeness_summary())
    assert summary["bound"] is True and summary["pages"] == 90 and summary["bands"] == 2
    assert summary["class_counts"] == sweep.class_counts
    assert summary["retained_facts_digest"] == digest
    assert sweep.digest == hashlib.sha256(sweep.completeness_summary().encode()).hexdigest()
    assert bound_sweep(census).digest == sweep.digest  # deterministic replay


def test_sweep_rejects_incomplete_foreign_or_extra_page_set(census):
    facts, digest, map_width, map_height = census
    requests, exchanges = exchanges_for(facts, map_width, map_height)
    record = TileClassificationSweep.record
    with pytest.raises(TileQueryError) as missing:
        record(
            requests,
            exchanges[:89],
            retained_facts=facts,
            retained_facts_digest=digest,
            retained_welcome=retained_welcome(map_width, map_height),
            observed_welcome=retained_welcome(map_width, map_height),
        )
    assert missing.value.code is TileFailure.INCOMPLETE_SWEEP
    with pytest.raises(TileQueryError) as extra:
        record(
            requests,
            exchanges + exchanges[:1],
            retained_facts=facts,
            retained_facts_digest=digest,
            retained_welcome=retained_welcome(map_width, map_height),
            observed_welcome=retained_welcome(map_width, map_height),
        )
    assert extra.value.code is TileFailure.INCOMPLETE_SWEEP
    forged = TileClassificationRequest(CENSUS_REQUEST_ID, Region(x=20, y=30, width=5, height=5), 0)
    with pytest.raises(TileQueryError) as foreign:
        record(
            (forged, *requests[1:]),
            exchanges,
            retained_facts=facts,
            retained_facts_digest=digest,
            retained_welcome=retained_welcome(map_width, map_height),
            observed_welcome=retained_welcome(map_width, map_height),
        )
    assert foreign.value.code is TileFailure.INCOMPLETE_SWEEP


def test_response_rejects_mislocated_rows(census):
    facts, _, map_width, map_height = census
    requests, exchanges = exchanges_for(facts, map_width, map_height)
    raw = json.loads(exchanges[1].response_payload)
    first, second = raw["tiles"][0], raw["tiles"][1]
    second[0] = first[0] + BAND.width  # jumps out of this page's ordinal slot
    with pytest.raises(TileQueryError) as mislocated:
        TileClassificationReceipt.correlate(requests[1].to_bytes(), json.dumps(raw).encode())
    # A coherent page stream cannot claim one tile twice: replaying a row out
    # of position already breaks the region-ordinal location contract, and
    # from_pages still dedupes defensively across pages.
    assert mislocated.value.code is TileFailure.INVALID_TILE


def test_sweep_flags_contradiction_fails_binding(census):
    victim = next(t for t in census[0].tiles if t.tree)
    inverted = flags15_from_fact(victim) ^ BIT["tree"]
    sweep = bound_sweep(census, patches={victim.tile_id: {"flags": inverted}})
    assert sweep.bound is False
    assert (victim.tile_id, "PROJECTED_FLAGS_DIFFER") in sweep.coherence_failures
    assert all(tile == victim.tile_id for tile, _ in sweep.coherence_failures)
    with pytest.raises(TileQueryError) as gate:
        sweep.require_bound()
    assert gate.value.code is TileFailure.ACCOUNTING_LIMIT_EXCEEDED


def test_sweep_industry_contradiction_fails_binding(census):
    facts = census[0]
    anchored = next(t for t in facts.tiles if t.industry_id is not None)
    consumed = next(
        t for t in facts.tiles if t.industry_id is None and t.tile_id != anchored.tile_id
    )
    drained = bound_sweep(census, patches={anchored.tile_id: {"industry": None}})
    assert failed_tiles(drained) == {(anchored.tile_id, "INDUSTRY_DIFFERS_FROM_TILE_FACT")}
    invented = bound_sweep(census, patches={consumed.tile_id: {"industry": 640 + consumed.tile_id}})
    assert failed_tiles(invented) == {(consumed.tile_id, "INDUSTRY_DIFFERS_FROM_TILE_FACT")}


def test_sweep_geometry_contradiction_fails_binding(census):
    facts = census[0]
    anchor = next(t for t in facts.tiles if t.buildable and not t.road and t.industry_id is None)
    raised = bound_sweep(census, patches={anchor.tile_id: {"elevation": anchor.min_height + 1}})
    assert failed_tiles(raised) == {(anchor.tile_id, "HEIGHT_DIFFERS_FROM_TILE_FACT")}
    sloped = bound_sweep(census, patches={anchor.tile_id: {"slope": anchor.slope ^ 0x1}})
    assert failed_tiles(sloped) == {(anchor.tile_id, "SLOPE_DIFFERS_FROM_TILE_FACT")}


def failed_tiles(sweep):
    return set(sweep.coherence_failures)


def test_sweep_world_identity_mismatch_blocks_binding(census):
    facts, _, map_width, map_height = census
    sweep = bound_sweep(
        census, observed_welcome=dict(retained_welcome(map_width, map_height), seed=18)
    )
    assert sweep.bound is False
    assert sweep.world_identity_mismatch is True
    assert (-1, "WORLD_IDENTITY_MISMATCH:seed") in sweep.coherence_failures


def test_projection_disagrees_truth_table(census):
    facts = census[0]
    plain = next(t for t in facts.tiles if t.buildable and not t.road and t.industry_id is None)
    base = flags15_from_fact(plain)
    assert plain.buildable is True
    assert projection_disagrees(plain, base) is False
    # The projected road bit is the OR of the three schema-2 road bits.
    assert projection_disagrees(plain, base | BIT["road_track"]) is True
    # House/station natively suppress the buildable projection; any single one
    # present flips parity for a buildable fact.
    assert projection_disagrees(plain, base | BIT["house"]) is True
    assert projection_disagrees(plain, base | BIT["station"]) is True
    # Transport bits carry over directly.
    assert projection_disagrees(plain, base | BIT["rail"]) is True
    assert projection_disagrees(plain, base | BIT["airport"]) is True
    # Ground bits carry over ones-for-one too.
    assert projection_disagrees(plain, base | BIT["water"]) is True
    railway = next(t for t in facts.tiles if t.rail and t.tile_id != plain.tile_id)
    rail_flags = flags15_from_fact(railway)
    assert railway.buildable is False
    assert projection_disagrees(railway, rail_flags) is False
    assert projection_disagrees(railway, rail_flags | BIT["buildable"]) is True


def test_v1_receipt_contract_unchanged():
    """Schema-1 observation receipts keep their exact ten-column convention."""
    request = TileFactsRequest("planning-n0-0", BAND, 0)

    def assessed(offset):
        """Neighbor mask exactly as the v1 response validates it."""
        return 2 | 4 | (0 if offset == 0 else 8)  # E|S always; W only past the edge

    rows = tuple(
        (BAND.y * 64 + BAND.x + offset, 1, 0, 1, None, -1, 0, 0, 0, assessed(offset))
        for offset in range(PAGE_SIZE)
    )
    response = TileFactsResponse(
        request.request_id,
        request.region,
        request.cursor,
        64,
        64,
        OBSERVED_DAYS,
        OBSERVED_DAYS,
        rows,
        PAGE_SIZE,
        True,
    )
    receipt = TileFactsReceipt.correlate(request.to_bytes(), response.to_bytes())
    assert receipt.request_id == "planning-n0-0"
    assert receipt.request_payload_sha256 == hashlib.sha256(request.to_bytes()).hexdigest()
    assert len(receipt.response_payload_sha256) == 64
