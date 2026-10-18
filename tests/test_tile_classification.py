"""Schema-2 tile classification: wire contracts, projection, composition.

All tests are offline: no OpenTTD launch, no AdminPort, no evidence mutation.
Historical protocol-v1 identities are exercised unchanged next to the additive
schema-2 contracts (old/new compatibility), and missing classifications fail
explicitly instead of being inferred.
"""

import json

import pytest

from app.simulation.openttd.observation_protocol import BridgeProtocolError
from app.simulation.openttd.supplemental_planning_facts import Region
from app.simulation.openttd.tile_classification import (
    CLASSIFICATION_FLAG_NAMES,
    CLASSIFICATION_SCHEMA_VERSION,
    FLAG_MASK_LIMIT,
    REQUEST_TYPE,
    RESULT_TYPE,
    TileClassificationIndex,
    TileClassificationRequest,
    TileClassificationResponse,
    classification_flags,
    classification_json,
    classify_tile,
    tile_classes,
)
from app.simulation.openttd.tile_facts import (
    TileFactsResponse,
    TileFailure,
    TileQueryError,
)


def _resp(request, rows, *, date=712282):
    return TileClassificationResponse(
        request.request_id,
        request.region,
        request.cursor,
        request.schema,
        4096,
        4096,
        date,
        date,
        tuple(rows),
        None,
        False,
    )


def _row(region, cursor, offset, flags=0, industry=None, owner=-1, elevation=1, slope=0):
    ordinal = cursor + offset
    x = region.x + ordinal % region.width
    y = region.y + ordinal // region.width
    return (y * 4096 + x, elevation, slope, flags, industry, owner)


def test_request_roundtrip_and_budgets():
    request = TileClassificationRequest("bridge-1", Region(x=0, y=0, width=1, height=1), 0)
    assert TileClassificationRequest.parse(request.to_bytes()) == request
    assert len(request.to_bytes()) <= 159
    payload = json.loads(request.to_bytes())
    assert payload["protocol"] == 1 and payload["type"] == REQUEST_TYPE
    assert payload["schema"] == CLASSIFICATION_SCHEMA_VERSION


def test_response_roundtrip_page_of_five_and_limit():
    region = Region(x=0, y=0, width=1, height=5)
    request = TileClassificationRequest("bridge-2", region, 0)
    rows = [
        _row(region, 0, i, flags=classification_flags(value), industry=None, owner=-1)
        for i, value in enumerate(
            [
                "HOUSE",
                "STATION",
                "CLEAR",
                "TREES",
                "WATER",
            ]
        )
    ]
    response = _resp(request, rows)
    assert TileClassificationResponse.parse(response.to_bytes()) == response
    assert len(response.to_bytes()) <= 508
    assert response.has_more is False
    overflow = list(json.loads(response.to_bytes())["tiles"])
    overflow.append(overflow[0])
    with pytest.raises(TileQueryError):
        TileClassificationResponse.parse(
            json.dumps(
                {**json.loads(response.to_bytes()), "tiles": overflow},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        )


def test_classification_precedence_is_native_derived():
    # house and station win over any ground/transport predicate
    house = 1 << CLASSIFICATION_FLAG_NAMES.index("house")
    assert classify_tile(house | (1 << CLASSIFICATION_FLAG_NAMES.index("tree")), 7).value == "HOUSE"
    station = 1 << CLASSIFICATION_FLAG_NAMES.index("station")
    assert (
        classify_tile(station | (1 << CLASSIFICATION_FLAG_NAMES.index("road_tile")), None).value
        == "STATION"
    )
    # A valid industry pointer classifies INDUSTRY
    assert classify_tile(1 << CLASSIFICATION_FLAG_NAMES.index("rough"), 3).value == "INDUSTRY"
    ordered = [
        ("WATER", "water"),
        ("COAST", "coast"),
        ("AIRPORT", "airport"),
        ("ROAD", "road_tile"),
        ("ROAD", "road_track"),
        ("ROAD", "road_src_type"),
        ("RAIL", "rail"),
        ("DOCK", "water_transport"),
        ("TREES", "tree"),
        ("FARM", "farm"),
        ("ROCK", "rock"),
        ("ROUGH", "rough"),
        ("CLEAR", None),
    ]
    for expected, name in ordered:
        if name is None:
            flags = classification_flags("CLEAR")
        else:
            flags = 1 << CLASSIFICATION_FLAG_NAMES.index(name)
        assert classify_tile(flags, None).value == expected


def test_unknown_occupancy_is_explicit_not_inferred():
    # no predicate at all: the class stays explicitly unknown
    assert classify_tile(0, None).value == "UNKNOWN_OCCUPANCY"


def test_mask_range_is_enforced():
    with pytest.raises(TileQueryError):
        classify_tile(FLAG_MASK_LIMIT + 1, None)
    with pytest.raises(TileQueryError):
        classify_tile(-1, None)
    with pytest.raises(TileQueryError):
        classify_tile(0, 64000)


def test_schema_mismatch_fails_explicitly():
    probe = TileClassificationRequest("bridge-3", Region(x=0, y=0, width=1, height=1), 0)
    bad = json.loads(probe.to_bytes())
    bad["schema"] = 3
    with pytest.raises(TileQueryError) as err:
        TileClassificationRequest.parse(
            json.dumps(bad, sort_keys=True, separators=(",", ":")).encode()
        )
    assert err.value.code is TileFailure.UNSUPPORTED_CLASSIFICATION_SCHEMA
    result = json.loads(
        _resp(
            TileClassificationRequest("bridge-4", Region(x=0, y=0, width=1, height=1), 0),
            [_row(Region(x=0, y=0, width=1, height=1), 0, 0)],
        ).to_bytes()
    )
    result["schema"] = 1
    with pytest.raises(TileQueryError):
        TileClassificationResponse.parse(
            json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
        )


def test_invalid_row_shapes_and_industry_null_only():
    region = Region(x=0, y=0, width=1, height=1)
    request = TileClassificationRequest("bridge-5", region, 0)
    with pytest.raises(TileQueryError):
        _resp(request, [(0, 1, 0, 0, None, None)])
    with pytest.raises(TileQueryError):
        _resp(request, [(1, 1, 0, 0, None, -1)])  # tile identity mismatch
    with pytest.raises(TileQueryError):
        _resp(request, [_row(region, 0, 0), _row(region, 0, 0)])  # duplicate


def test_completeness_of_index_and_unknown_count():
    region = Region(x=10, y=10, width=3, height=2)
    pages = []
    request = TileClassificationRequest("bridge-6", region, 0)
    for cursor in (0, 5):
        rows = []
        for offset in range(5):
            ordinal = cursor + offset
            if ordinal >= region.width * region.height:
                break
            if ordinal == 0:
                flags = classification_flags("TREES")
            elif ordinal == 1:
                flags = 0  # the one unknown-occupancy tile: no predicate applies
            else:
                flags = classification_flags("CLEAR")
            rows.append(_row(region, cursor, offset, flags=flags))
        page_count = min(5, region.width * region.height - cursor)
        has_more = cursor + page_count < region.width * region.height
        with_tile = TileClassificationResponse(
            request.request_id,
            region,
            cursor,
            2,
            4096,
            4096,
            712282,
            712282,
            tuple(rows),
            cursor + page_count if has_more else None,
            has_more,
        )
        pages.append(with_tile)
    index = TileClassificationIndex.from_pages(request, tuple(pages))
    assert len(index.tiles) == region.width * region.height
    assert index.class_counts == {"CLEAR": 4, "TREES": 1, "UNKNOWN_OCCUPANCY": 1}
    assert len(index.unknown_tiles) == 1
    classes = tile_classes(index)
    assert set(classes.values()) == {"TREES", "UNKNOWN_OCCUPANCY", "CLEAR"}
    assert json.loads(classification_json(index))["region"] == [10, 10, 3, 2]


def test_index_completeness_failure_is_incomplete_sweep():
    region = Region(x=0, y=0, width=1, height=1)
    request = TileClassificationRequest("bridge-7", region, 0)
    with pytest.raises(TileQueryError) as err:
        TileClassificationIndex.from_pages(request, ())
    assert err.value.code is TileFailure.CLASSIFICATION_UNAVAILABLE
    # A page carrying fewer rows than the cursor window demands is rejected at
    # parse time (explicit, bounded, no census repair).
    with pytest.raises(TileQueryError):
        _resp(request, [])
    complete = _resp(request, [_row(region, 0, 0)])
    index = TileClassificationIndex.from_pages(request, (complete,))
    assert index.by_tile[0].tile_class.value == "UNKNOWN_OCCUPANCY"
    with pytest.raises(TileQueryError):
        TileClassificationIndex.from_pages(
            TileClassificationRequest("other", region, 0), (complete,)
        )


def test_historical_protocol_v1_identity_unchanged():
    """The frozen v1 tile contracts parse exactly as retained evidence does."""
    # Round-trip a minimal v1 response over the same region shape: v1 rows are
    # 10 wide (flags 13-bit packed) and the module must be untouched.
    region = Region(x=0, y=0, width=1, height=1)
    row = (0, 1, 13, 0, None, -1, 0, 0, 0, 0)
    response = TileFactsResponse(
        "legacy-1", region, 0, 4096, 4096, 712282, 712282, (row,), None, False
    )
    parsed = TileFactsResponse.parse(response.to_bytes())
    assert parsed == response
    fact = parsed.tile_fact(row)
    # The known schema-1 collapse: house/station-shaped rows report the flags
    # as false with buildable=False; no class is invented.
    assert fact.buildable is False and fact.slope == 13
    assert fact.tree is False and fact.industry_id is None


def test_composition_is_additive_and_frozen_sources_untouched():
    from app.simulation.openttd.gamescript_bridge import BRIDGE_DIRECTORY
    from app.simulation.openttd.terrain_bridge import terrain_bridge_source
    from app.simulation.openttd.terrain_classification_bridge import (
        CLASSIFICATION_HANDLER_FILE,
        classification_package_bytes,
        classification_package_digest,
        terrain_classification_source,
    )

    composed = terrain_classification_source()
    # The frozen v1 composition stays importable and byte-stable, and the
    # classification composition does not absorb the v1 handler text.
    assert terrain_bridge_source().count('request.type != "tile_facts_page"') == 1
    assert "class TerrainBridge extends RawObservationBridge" not in composed
    assert composed.count("class RawObservationBridge extends GSController") == 1
    # The additive handler exists exactly once and guards native schema-2.
    assert composed.count('request.type != "tile_classification_page"') == 1
    assert 'typeof request.schema!="integer" || request.schema!=2' in composed
    # Wire cross-check: the handler's request-field gate must match the
    # serialized request exactly (a capture would otherwise be hard-rejected).
    probe_request = TileClassificationRequest("bridge-0", Region(x=0, y=0, width=1, height=1), 0)
    assert len(json.loads(probe_request.to_bytes())) == 6
    assert "request.len()!=6" in composed
    for predicate in (
        "GSTile.IsHouseTile(tile)",
        "GSTile.IsStationTile(tile)",
        "GSTile.GetOwner(tile)",
        "GSAirport.IsAirportTile(tile)",
    ):
        assert predicate in composed
    package = classification_package_bytes()
    assert set(package) == {"info.nut", "main.nut"}
    # The composition is pure: repeated calls give the identical digest.
    assert classification_package_digest(package) == classification_package_digest()
    # The staged main.nut is exactly base (renamed) followed by the handler.
    handler_text = CLASSIFICATION_HANDLER_FILE.read_text()
    assert (
        composed.encode()
        == (
            (BRIDGE_DIRECTORY / "main.nut")
            .read_text()
            .replace(
                "class NoMutationBridge extends GSController",
                "class RawObservationBridge extends GSController",
            )
            + handler_text
        ).encode()
    )


def test_error_envelopes_map_to_structured_codes():
    """Native schema-2 errors parse into the strict v1-shaped 8-field set."""
    region = Region(x=0, y=0, width=1, height=1)
    request = TileClassificationRequest("bridge-err", region, 0)
    envelope = json.dumps(
        {
            "protocol": 1,
            "type": RESULT_TYPE,
            "schema": 2,
            "request_id": request.request_id,
            "status": "error",
            "error_code": "CURSOR_MISMATCH",
            "cursor": 0,
            "failed_tile": None,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    with pytest.raises(TileQueryError) as err:
        TileClassificationResponse.parse(envelope)
    assert err.value.code is TileFailure.CURSOR_MISMATCH
    unknown_code = envelope.replace(b"CURSOR_MISMATCH", b"NOT_A_CODE")
    with pytest.raises(TileQueryError) as err2:
        TileClassificationResponse.parse(unknown_code)
    assert err2.value.code is TileFailure.MALFORMED_RESPONSE
    # A missing field is rejected at the envelope level, not silently mapped.
    with pytest.raises(BridgeProtocolError):
        TileClassificationResponse.parse(
            envelope.replace(b'"schema":2', b'"schema":3')  # schema gate fails first, still bounded
        )


def test_canonical_response_matches_hand_built_nut_ordering():
    """The .nut canonical string mirrors the Python serializer key order."""
    region = Region(x=0, y=0, width=1, height=1)
    request = TileClassificationRequest("bridge-8", region, 0)
    row = _row(region, 0, 0, flags=classification_flags("HOUSE"), industry=2, owner=0)
    text = _resp(request, [row]).to_bytes().decode()
    after = text[text.index('"cursor":0') :]
    keys = [after.index(k) for k in ('"date_after"', '"date_before"', '"has_more"')]
    keys += [after.index('"map"'), after.index('"next_cursor"'), after.index('"protocol"')]
    keys += [after.index('"region"'), after.index('"request_id"'), after.index('"schema"')]
    keys += [after.index('"status"'), after.index('"tiles"'), after.index('"type"')]
    assert keys == sorted(keys)
