"""Public wire admission: no native client or solver."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.simulation.openttd.supplemental_planning_facts import Region
from app.simulation.openttd.tile_facts import (
    TileFactsReceipt,
    TileFactsRequest,
    TileFactsResponse,
    TileFailure,
    TileQueryError,
)


def test_request_roundtrip():
    request = TileFactsRequest("tile-001", Region(x=0, y=0, width=1, height=1), 0)
    assert TileFactsRequest.parse(request.to_bytes()) == request
    assert len(request.to_bytes()) <= 159


def response():
    r = Region(x=4000, y=4000, width=15, height=17)
    q = TileFactsRequest("x" * 64, r, 250)
    rows = []
    for i in range(250, 255):
        x = r.x + i % r.width
        y = r.y + i // r.width
        mask = (
            (1 if y > r.y else 0)
            | (2 if x < r.x + r.width - 1 else 0)
            | (4 if y < r.y + r.height - 1 else 0)
            | (8 if x > r.x else 0)
        )
        rows.append((y * 4096 + x, 255, 31, 8191, 63999, -1, 1, mask, mask, mask))
    return q, TileFactsResponse(
        q.request_id, r, 250, 4096, 4096, 2147483647, 2147483647, tuple(rows), None, False
    )


def test_five_rows_exact_width_and_six_overflow():
    vector = json.loads(Path("tests/fixtures/p08_terrain_road_design.json").read_text())

    def dump(o):
        return json.dumps(o, sort_keys=True, separators=(",", ":")).encode()

    assert len(dump(vector["maximum_width_request"])) == 159
    assert len(dump(vector["maximum_width_response"])) == 508
    d = vector["maximum_width_response"]
    d["tiles"].append(d["tiles"][0])
    assert len(dump(d)) == 551
    with pytest.raises(TileQueryError):
        TileFactsResponse.parse(dump(d))
    q, r = response()
    assert len(q.to_bytes()) == 159 and len(r.to_bytes()) <= 508
    assert TileFactsResponse.parse(r.to_bytes()) == r
    assert TileFactsReceipt.correlate(q.to_bytes(), r.to_bytes()).request_id == q.request_id


@pytest.mark.parametrize(
    "field,value",
    [
        ("protocol", 2),
        ("cursor", 249),
        ("has_more", True),
        ("next_cursor", 255),
        ("map", [8192, 4096]),
        ("date_after", -1),
        ("request_id", 'a"b'),
        ("status", "no"),
        ("extra", 0),
    ],
)
def test_strict_response_rejection(field, value):
    q, r = response()
    d = json.loads(r.to_bytes())
    d[field] = value
    with pytest.raises(ValueError):
        TileFactsResponse.parse(json.dumps(d, separators=(",", ":")).encode())


@pytest.mark.parametrize(
    "column,value",
    [
        (0, -1),
        (1, -1),
        (1, 256),
        (2, 65535),
        (3, 8192),
        (4, 64000),
        (5, 15),
        (6, 2),
        (7, 16),
        (8, -1),
        (9, 0),
    ],
)
def test_tile_scalar_unknown_rejected(column, value):
    q, r = response()
    rows = [list(x) for x in r.rows]
    rows[0][column] = value
    with pytest.raises(TileQueryError):
        replace(r, rows=tuple(tuple(x) for x in rows))


@pytest.mark.parametrize(
    "region,cursor",
    [
        (Region(x=0, y=0, width=1, height=1), 1),
        (Region(x=0, y=0, width=16, height=16), 1),
        (Region(x=4095, y=0, width=2, height=1), 0),
    ],
)
def test_request_map_and_cursor(region, cursor):
    with pytest.raises(TileQueryError):
        TileFactsRequest("tile", region, cursor).require_map(4096, 4096)


def test_bounded_native_error_and_wrong_identity():
    q, _ = response()
    d = dict(
        protocol=1,
        type="tile_facts_page_result",
        status="error",
        request_id=q.request_id,
        error_code="INVALID_TILE",
        cursor=250,
        failed_tile=16777215,
    )
    p = json.dumps(d, separators=(",", ":")).encode()
    assert len(p) < 227
    with pytest.raises(TileQueryError) as err:
        TileFactsReceipt.correlate(q.to_bytes(), p)
    assert err.value.code is TileFailure.INVALID_TILE
    d["request_id"] = "other"
    with pytest.raises(TileQueryError) as err:
        TileFactsReceipt.correlate(q.to_bytes(), json.dumps(d).encode())
    assert err.value.code is TileFailure.REQUEST_ID_MISMATCH


def test_receipt_rejects_oversize_before_json_decode(monkeypatch):
    q, _ = response()
    original = json.loads

    def bounded_decode(payload, *args, **kwargs):
        assert len(payload) <= 512, "unbounded response reached JSON decoder"
        return original(payload, *args, **kwargs)

    monkeypatch.setattr(json, "loads", bounded_decode)
    with pytest.raises(TileQueryError) as error:
        TileFactsReceipt.correlate(q.to_bytes(), b" " * 513)
    assert error.value.code is TileFailure.RESPONSE_LIMIT_EXCEEDED
