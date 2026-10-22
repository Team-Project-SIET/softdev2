"""Executable design arithmetic/assertions, not a handler or acquisition collector."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from test_supplemental_planning_contracts import fact_dict, world_for

from app.simulation.openttd.supplemental_planning_facts import (
    PlanningFactError,
    Region,
    SupplementalPlanningFacts,
    TileFact,
)

DESIGN = json.loads((Path(__file__).parent / "fixtures/p08_terrain_road_design.json").read_bytes())


def serialized(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def test_exact_field_width_payload_arithmetic():
    assert DESIGN["classification"] == "DESIGN_CALCULATION_ONLY"
    assert len(serialized(DESIGN["maximum_width_request"])) == 159
    response = deepcopy(DESIGN["maximum_width_response"])
    assert len(serialized(response)) == 508 <= 512 < 1450
    assert len(serialized(response["tiles"][0])) == 42
    response["tiles"] = []
    assert len(serialized(response)) == 294
    response["tiles"] = DESIGN["maximum_width_response"]["tiles"] + [
        DESIGN["maximum_width_response"]["tiles"][0]
    ]
    assert len(serialized(response)) == 551 > 512
    assert len(serialized(DESIGN["maximum_width_error"])) == DESIGN["maximum_error_bytes"] <= 255


@pytest.mark.parametrize("n", [1, 5, 6, 255, 256])
def test_ordinal_pagination_is_complete_and_deterministic(n):
    starts = list(range(0, n, 5))
    pages = [tuple(range(start, min(start + 5, n))) for start in starts]
    assert tuple(i for page in pages for i in page) == tuple(range(n))
    assert len(pages) == (n + 4) // 5 <= 52
    assert starts == sorted(starts) and all(len(page) == 5 for page in pages[:-1])
    assert [start + len(page) for start, page in zip(starts, pages)][-1] == n


def test_two_sweep_design_budget_arithmetic():
    pages = (256 + 4) // 5
    requests = 2 * pages
    assert pages == 52 and requests == 104
    assert requests * 508 == 52832
    assert requests * 4 == 416
    assert requests * 8 == 832
    assert 2 + 3 + requests * 8 + 1 == 838
    assert 2 * 256 * 44 + requests * 6 == 23152


@pytest.mark.parametrize("defect", ["duplicate", "missing", "reordered", "cursor", "source"])
def test_draft_page_admission_assertions_reject_bad_design_vectors(defect):
    # Test-only assertions over invented vectors specify future admission behavior.
    # They are not a persisted transport DTO/parser or a production collector.
    expected = list(range(6))
    pages: list[dict[str, Any]] = [
        dict(cursor=0, rows=[0, 1, 2, 3, 4], source="owned"),
        dict(cursor=5, rows=[5], source="owned"),
    ]
    if defect == "duplicate":
        pages[1]["rows"] = [4]
    if defect == "missing":
        pages.pop()
    if defect == "reordered":
        pages.reverse()
    if defect == "cursor":
        pages[1]["cursor"] = 4
    if defect == "source":
        pages[1]["source"] = "other-runtime"
    with pytest.raises(AssertionError):
        assert [page["cursor"] for page in pages] == [0, 5]
        assert all(page["source"] == "owned" for page in pages)
        assert [row for page in pages for row in page["rows"]] == expected


@pytest.fixture(scope="module")
def world():
    return world_for()


def full_region(world):
    d = fact_dict(world)
    d["region"] = dict(x=0, y=0, width=16, height=16)
    prototype = d["tiles"][0]
    d["tiles"] = [
        dict(prototype, tile_id=y * d["source"]["map_width"] + x, x=x, y=y)
        for y in range(16)
        for x in range(16)
    ]
    return d


@pytest.mark.parametrize("defect", ["duplicate", "missing", "source"])
def test_existing_domain_rejects_incomplete_or_wrong_source_region(world, defect):
    d = full_region(world)
    if defect == "duplicate":
        d["tiles"][-1] = d["tiles"][0]
    if defect == "missing":
        d["tiles"].pop()
    if defect == "source":
        d["source"]["runtime_digest"] = "0" * 64
    with pytest.raises((PlanningFactError, ValidationError)):
        facts = SupplementalPlanningFacts.model_validate_json(serialized(d))
        facts.require_world(world)


def test_existing_region_limit_and_coordinate_boundaries(world):
    facts = SupplementalPlanningFacts.model_validate_json(serialized(full_region(world)))
    facts.require_world(world)
    assert len(facts.tiles) == 256 and facts.tiles[0].tile_id == 0
    with pytest.raises(ValidationError):
        Region(x=0, y=0, width=17, height=16)
    # Native landscape initializes the south/east edges MP_VOID; this synthetic
    # numeric test is not a claim that tile 0 is valid in every freeform-edge world.
    width = height = 4096
    maximum_regular_index = (height - 2) * width + width - 2
    assert maximum_regular_index == 16773118 < width * height - 1 == 16777215
    tile = facts.tiles[0].model_dump()
    tile.update(tile_id=maximum_regular_index, x=4094, y=4094)
    assert TileFact.model_validate(tile).tile_id == maximum_regular_index


@pytest.mark.parametrize(
    "a,b,expected", [((11, 1), (16, 1), (10, 0, 8, 3)), ((1, 1), (100, 100), None)]
)
def test_bounded_anchor_rectangle_selection(a, b, expected):
    x0, y0 = max(0, min(a[0], b[0]) - 1), max(0, min(a[1], b[1]) - 1)
    x1, y1 = min(127, max(a[0], b[0]) + 1), min(127, max(a[1], b[1]) + 1)
    rectangle = (x0, y0, x1 - x0 + 1, y1 - y0 + 1)
    if expected is None:
        assert rectangle[2] * rectangle[3] > 256
        with pytest.raises(ValidationError):
            Region(x=rectangle[0], y=rectangle[1], width=rectangle[2], height=rectangle[3])
    else:
        assert rectangle == expected
        assert Region(x=x0, y=y0, width=rectangle[2], height=rectangle[3]).width == 8
