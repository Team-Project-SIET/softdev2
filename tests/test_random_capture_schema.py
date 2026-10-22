"""Explicit larger random captures preserve the fixed capture contract."""

import hashlib
import json

import pytest
from pydantic import ValidationError
from test_supplemental_planning_contracts import fact_dict, world_for

from app.simulation.openttd.supplemental_planning_facts import (
    RandomCaptureRegion,
    Region,
    SupplementalPlanningFacts,
)


@pytest.fixture(scope="module")
def capture():
    data = fact_dict(world_for())
    data["source"].update(map_width=256, map_height=256)
    data["region"] = {
        "x": 0,
        "y": 0,
        "width": 150,
        "height": 3,
        "profile": "random-rectangle-512-v1",
    }
    template = data["tiles"][0]
    data["tiles"] = [
        dict(template, tile_id=y * 256 + x, x=x, y=y) for y in range(3) for x in range(150)
    ]
    data["coverage_scopes"] = [dict(industry_id=2, cargo_id=1, role="pickup")]
    data["coverage"] = [
        dict(
            tile_id=t["tile_id"],
            industry_id=2,
            cargo_id=1,
            role="pickup",
            producer_count=1,
            acceptance_eighths=0,
            industry_covered=True,
        )
        for t in data["tiles"]
    ]
    return data


def parse(data):
    return SupplementalPlanningFacts.model_validate_json(json.dumps(data))


def test_extended_complete_capture_accepted(capture):
    result = parse(capture)
    assert isinstance(result.region, RandomCaptureRegion)
    assert len(result.tiles) == len(result.coverage) == 450
    assert parse(json.loads(result.model_dump_json())) == result


@pytest.mark.parametrize("profile", [None, "random-rectangle-1024-v1"])
def test_extended_requires_supported_profile(capture, profile):
    data = json.loads(json.dumps(capture))
    if profile is None:
        del data["region"]["profile"]
    else:
        data["region"]["profile"] = profile
    with pytest.raises(ValidationError):
        parse(data)


def test_fixed_region_rejects_450_tiles():
    with pytest.raises(ValidationError, match="region exceeds 256 tiles"):
        Region(x=0, y=0, width=150, height=3)


@pytest.mark.parametrize("width,height", [(171, 3), (513, 1), (1, 513)])
def test_extended_budget_rejected(width, height):
    with pytest.raises(ValidationError):
        RandomCaptureRegion(x=0, y=0, width=width, height=height, profile="random-rectangle-512-v1")


@pytest.mark.parametrize("field", ["tiles", "coverage"])
def test_extended_requires_complete_observations(capture, field):
    data = json.loads(json.dumps(capture))
    data[field].pop()
    with pytest.raises(ValidationError, match="incomplete"):
        parse(data)


def test_fixed_serialization_unchanged():
    region = Region(x=0, y=0, width=16, height=16)
    expected = '{"x":0,"y":0,"width":16,"height":16}'
    assert region.model_dump_json() == expected
    assert (
        hashlib.sha256(region.model_dump_json().encode()).digest()
        == hashlib.sha256(expected.encode()).digest()
    )
    data = fact_dict(world_for())
    result = parse(data)
    assert result.region.model_dump() == data["region"]
    assert "profile" not in result.model_dump()["region"]
