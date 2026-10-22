"""Deterministic offline checks; none starts OpenTTD or opens AdminPort."""

import json
from types import SimpleNamespace as NS

import pytest
from pydantic import ValidationError

from app import openttd_demo as demo
from app.demo_random import (
    DemoBudgets,
    RandomWorldSettings,
    discover_relationships,
    plan_packages,
    prepare_random,
    relationship_region,
)


@pytest.mark.parametrize(
    "seed,climate,terrain",
    [(0, "temperate", 0), (42, "arctic", 2), (98765, "tropic", 5), (123, "toyland", 1)],
)
def test_reproducible_native_generator_recipe(tmp_path, seed, climate, terrain):
    settings = RandomWorldSettings(seed=seed, climate=climate, terrain=terrain)
    for name in ("a", "b"):
        prepare_random(tmp_path / name, settings, DemoBudgets())
    assert (tmp_path / "a/generation.cfg").read_bytes() == (
        tmp_path / "b/generation.cfg"
    ).read_bytes()
    a = json.loads((tmp_path / "a/experiment.json").read_text())
    b = json.loads((tmp_path / "b/experiment.json").read_text())
    assert a == b
    assert a["actual_world_identity"] is None and a["actual_generation_settings"] is None
    assert not a["native_execution_ready"]
    assert "map_x = 8" in settings.config() and "heightmap" not in settings.config()
    with pytest.raises(FileExistsError):
        prepare_random(tmp_path / "a", settings, DemoBudgets())


@pytest.mark.parametrize("value", [-1, 4294967295, True])
def test_invalid_seed_rejected(value):
    with pytest.raises(ValidationError):
        RandomWorldSettings(seed=value)


def observed_world(count=8, *, production=90, distant=False):
    return NS(
        context=NS(world=NS(map_width=256, map_height=256)),
        structural=NS(
            capability=NS(
                observation=NS(
                    capabilities=[
                        NS(
                            industry_id=i,
                            produces=(7,) if i % 2 == 0 else (),
                            accepts=(7,) if i % 2 else (),
                        )
                        for i in range(count)
                    ]
                )
            ),
            inventory=NS(
                observation=NS(
                    records=[
                        NS(id=i, x=10 + (i * 100 if distant else i), y=12) for i in range(count)
                    ]
                )
            ),
            catalog=NS(observation=NS(records=[NS(cargo_id=7, is_freight=True)])),
        ),
        production=NS(
            records=[
                NS(industry_id=i, cargo_id=7, last_month_produced=production)
                for i in range(0, count, 2)
            ]
        ),
    )


def test_observed_industries_and_non_coal_cargo_have_variable_counts():
    two = discover_relationships(observed_world(2), DemoBudgets())
    eight = discover_relationships(observed_world(), DemoBudgets())
    assert two.relationships == ((0, 1, 7),)
    assert len(eight.relationships) == 16
    assert eight.status == "CANDIDATES_REQUIRE_P08"
    assert all(cargo == 7 for _, _, cargo in eight.relationships)


def test_zero_supply_unsupported_geometry_and_search_budget_are_distinct():
    empty = discover_relationships(observed_world(production=0), DemoBudgets())
    assert empty.status == "NO_SUPPORTED_RELATIONSHIP" and not empty.relationships
    unsupported = discover_relationships(observed_world(2, distant=True), DemoBudgets())
    assert unsupported.status == "CANDIDATES_REQUIRE_P08"
    with pytest.raises(ValueError, match="CAPTURE_TILE_BUDGET"):
        relationship_region(observed_world(2, distant=True), unsupported.relationships[0])
    limited = discover_relationships(observed_world(), DemoBudgets(max_pair_checks=1))
    assert limited.status == "SEARCH_LIMIT" and limited.checks == 1
    with pytest.raises(ValueError, match="NO_SUPPORTED_RELATIONSHIP"):
        plan_packages((), DemoBudgets())


def test_random_cli_prepares_without_native_and_forwards_explicit_run(
    tmp_path, monkeypatch, capsys
):
    def forbidden(*a, **k):
        pytest.fail("random path invoked fixed native runner")

    monkeypatch.setattr(demo, "RUNS", tmp_path)
    monkeypatch.setattr(demo.native, "prepare", forbidden)
    monkeypatch.setattr(demo.native, "run", forbidden)
    assert demo.main(["plan", "--random-world", "--seed", "123", "--max-services", "8"]) == 0
    assert "PREPARED_RECIPE_ONLY" in capsys.readouterr().out
    forwarded = []
    monkeypatch.setattr(demo, "run_demo", lambda **kwargs: forwarded.append(kwargs) or 0)
    assert demo.main(["run", "--random-world", "--headless", "--seed", "123"]) == 0
    assert forwarded[0]["random_world"]["seed"] == 123
    with pytest.raises(SystemExit):
        demo.main(["plan", "--seed", "12"])
    with pytest.raises(SystemExit):
        demo.main(["plan", "--random-world", "--map-size", "512"])
