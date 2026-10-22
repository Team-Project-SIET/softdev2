"""Controlled synthetic pages through the pure pagination boundary."""

import hashlib
import json
from dataclasses import replace

import pytest

from app.simulation.openttd.supplemental_planning_facts import Region
from app.simulation.openttd.terrain_pagination import PaginationBudget, TerrainPagination
from app.simulation.openttd.tile_facts import TileFactsExchange, TileFactsReceipt, TileFactsResponse


def exchange(q, width=64, height=64):
    rows = []
    for i in range(q.cursor, min(q.cursor + 5, q.region.width * q.region.height)):
        x, y = q.region.x + i % q.region.width, q.region.y + i // q.region.width
        mask = sum(
            1 << bit
            for bit, (dx, dy) in enumerate(((0, -1), (1, 0), (0, 1), (-1, 0)))
            if q.region.x <= x + dx < q.region.x + q.region.width
            and q.region.y <= y + dy < q.region.y + q.region.height
        )
        rows.append((y * width + x, 0, 0, 1, None, -1, 0, 0, 0, mask))
    more = q.cursor + len(rows) < q.region.width * q.region.height
    r = TileFactsResponse(
        q.request_id,
        q.region,
        q.cursor,
        width,
        height,
        0,
        0,
        tuple(rows),
        q.cursor + len(rows) if more else None,
        more,
    ).to_bytes()
    payload = q.to_bytes()
    return TileFactsExchange(payload, r, TileFactsReceipt.correlate(payload, r))


def test_single_page_complete_assembly():
    pages = TerrainPagination(Region(x=1, y=1, width=5, height=1), 64, 64)
    assert [q.cursor for q in pages.requests] == [0]
    pages.accept(exchange(pages.requests[0]))
    result = pages.finish()
    assert [r[0] for r in result.rows] == [65, 66, 67, 68, 69]
    assert result.metadata["complete"] is True
    assert result.metadata["received_pages"] == [pages.requests[0].request_id]


def test_partial_final_page_and_accounting():
    pages = TerrainPagination(Region(x=1, y=1, width=4, height=3), 64, 64)
    assert [q.cursor for q in pages.requests] == [0, 5, 10]
    for q in pages.requests:
        pages.accept(exchange(q))
    result = pages.finish()
    assert [r[0] for r in result.rows] == [65, 66, 67, 68, 129, 130, 131, 132, 193, 194, 195, 196]
    assert result.metadata["tile_count"] == 12
    assert result.metadata["request_bytes"] == sum(len(e.request_payload) for e in result.exchanges)
    assert result.metadata["response_bytes"] == sum(
        len(e.response_payload) for e in result.exchanges
    )
    assert result.metadata["query_operations"] == 12


def test_cumulative_response_budget_rejects_without_dataset():
    pages = TerrainPagination(
        Region(x=1, y=1, width=6, height=1),
        64,
        64,
        budget=PaginationBudget(max_response_bytes=508),
    )
    pages.accept(exchange(pages.requests[0]))
    with pytest.raises(ValueError, match="budget"):
        pages.accept(exchange(pages.requests[1]))
    with pytest.raises(ValueError, match="coverage"):
        pages.finish()


@pytest.mark.parametrize(
    "tiles,cursors", [(1, [0]), (5, [0]), (6, [0, 5]), (10, [0, 5]), (256, list(range(0, 256, 5)))]
)
def test_bounded_enumeration_and_complete_assembly(tiles, cursors):
    region = Region(x=1, y=1, width=16 if tiles == 256 else tiles, height=16 if tiles == 256 else 1)
    pages = TerrainPagination(region, 512, 512)
    assert [q.cursor for q in pages.requests] == cursors
    assert len({q.request_id for q in pages.requests}) == len(cursors)
    for q in pages.requests:
        pages.accept(exchange(q, 512, 512))
    result = pages.finish()
    assert len(result.rows) == tiles
    assert len({r[0] for r in result.rows}) == tiles
    assert (
        result.metadata["rows_sha256"]
        == hashlib.sha256(
            json.dumps(result.rows, separators=(",", ":")).encode("ascii")
        ).hexdigest()
    )
    assert result.metadata["expected_pages"] == result.metadata["received_pages"]


@pytest.mark.parametrize(
    "defect",
    [
        "missing",
        "duplicate",
        "conflicting_duplicate",
        "out_of_order",
        "wrong_request",
        "wrong_map",
        "malformed",
        "extra",
    ],
)
def test_bad_pages_never_publish_complete_dataset(defect):
    pages = TerrainPagination(Region(x=1, y=1, width=6, height=1), 64, 64)
    first = exchange(pages.requests[0])
    if defect == "missing":
        pages.accept(first)
    else:
        bad = first
        if defect == "out_of_order":
            bad = exchange(pages.requests[1])
        elif defect == "wrong_request":
            bad = exchange(replace(pages.requests[0], request_id="other"))
        elif defect == "wrong_map":
            bad = exchange(pages.requests[0], 128, 64)
        elif defect == "malformed":
            bad = replace(first, response_payload=b"not json")
        elif defect in ("duplicate", "conflicting_duplicate", "extra"):
            pages.accept(first)
            if defect == "conflicting_duplicate":
                obj = json.loads(first.response_payload)
                obj["tiles"][0][1] = 1
                raw = json.dumps(obj, separators=(",", ":")).encode()
                bad = replace(
                    first,
                    response_payload=raw,
                    receipt=TileFactsReceipt.correlate(first.request_payload, raw),
                )
            if defect == "extra":
                pages.accept(exchange(pages.requests[1]))
        with pytest.raises(ValueError):
            pages.accept(bad)
    with pytest.raises(ValueError, match="coverage"):
        pages.finish()


@pytest.mark.parametrize(
    "defect",
    [
        "overlap",
        "outside",
        "missing_row",
        "duplicate_tile",
        "wrong_region",
        "bad_cursor",
        "bad_terminal",
    ],
)
def test_invalid_synthetic_response_rejected(defect):
    pages = TerrainPagination(Region(x=1, y=1, width=6, height=1), 64, 64)
    pages.accept(exchange(pages.requests[0]))
    ex = exchange(pages.requests[1])
    obj = json.loads(ex.response_payload)
    if defect == "overlap":
        obj["tiles"][0][0] = 65
    elif defect == "outside":
        obj["tiles"][0][0] = 71
    elif defect == "missing_row":
        obj["tiles"] = []
    elif defect == "duplicate_tile":
        obj["tiles"].append(obj["tiles"][0])
    elif defect == "wrong_region":
        obj["region"] = [2, 1, 6, 1]
    elif defect == "bad_cursor":
        obj["cursor"] = 0
    else:
        obj["has_more"] = True
        obj["next_cursor"] = 10
    raw = json.dumps(obj, separators=(",", ":")).encode()
    # Correlation is intentionally invalid: production admission must reject the raw bytes.
    with pytest.raises(ValueError):
        pages.accept(replace(ex, response_payload=raw))
    with pytest.raises(ValueError):
        pages.finish()


@pytest.mark.parametrize(
    "field,value",
    [
        ("page_request_bytes", 1),
        ("page_response_bytes", 1),
        ("max_request_bytes", 1),
        ("max_response_bytes", 1),
        ("max_operations", 1),
    ],
)
def test_page_and_cumulative_admission_budget(field, value):
    pages = TerrainPagination(
        Region(x=1, y=1, width=1, height=1), 64, 64, budget=PaginationBudget(**{field: value})
    )
    with pytest.raises(ValueError, match="budget"):
        pages.accept(exchange(pages.requests[0]))
    with pytest.raises(ValueError):
        pages.finish()


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_pages", 53),
        ("max_pages", True),
        ("page_request_bytes", 160),
        ("page_response_bytes", 509),
        ("max_request_bytes", 8269),
        ("max_response_bytes", 26417),
        ("max_operations", 417),
        ("max_operations", 0),
    ],
)
def test_budget_cannot_exceed_design(field, value):
    with pytest.raises(ValueError):
        PaginationBudget(**{field: value})


def test_insufficient_page_budget_rejects_plan():
    with pytest.raises(ValueError, match="budget"):
        TerrainPagination(
            Region(x=1, y=1, width=6, height=1), 64, 64, budget=PaginationBudget(max_pages=1)
        )


def test_cumulative_request_and_operation_budget():
    region = Region(x=1, y=1, width=6, height=1)
    default = TerrainPagination(region, 64, 64)
    for budget in (
        PaginationBudget(max_operations=4),
        PaginationBudget(max_request_bytes=len(default.requests[0].to_bytes())),
    ):
        pages = TerrainPagination(region, 64, 64, budget=budget)
        pages.accept(exchange(pages.requests[0]))
        with pytest.raises(ValueError, match="budget"):
            pages.accept(exchange(pages.requests[1]))
        with pytest.raises(ValueError):
            pages.finish()


def test_progress_tracks_expected_received_and_missing_identities():
    pages = TerrainPagination(Region(x=1, y=1, width=6, height=1), 64, 64)
    pages.accept(exchange(pages.requests[0]))
    assert pages.progress == {
        "expected_pages": ["terrain-p001", "terrain-p002"],
        "received_pages": ["terrain-p001"],
        "missing_pages": ["terrain-p002"],
        "failed": False,
    }


def test_mutable_payload_cannot_change_admitted_observations():
    pages = TerrainPagination(Region(x=1, y=1, width=1, height=1), 64, 64)
    ex = exchange(pages.requests[0])
    with pytest.raises(ValueError, match="bytes"):
        pages.accept(replace(ex, response_payload=bytearray(ex.response_payload)))
    with pytest.raises(ValueError):
        pages.finish()
