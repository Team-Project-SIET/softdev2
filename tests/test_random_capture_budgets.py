"""Offline budget sealing and legacy package correspondence; native is prohibited."""

import asyncio
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_demo_random_native import prohibit_native  # noqa: F401
from test_random_distance import controlled_input

from app.demo_random import DemoBudgets, RandomWorldSettings
from app.demo_random_native import random_budgets, stage_random
from app.simulation.openttd.freight_runtime_planning import PlanningReadback, capture_planning_facts
from app.simulation.openttd.proof import freight_delivery as native

RUN = Path("artifacts/demos/playable-demo-b84b9bd854a342f1a86e4ba669d8e450")


@pytest.mark.parametrize("relationships", [1, 16])
def test_explicit_and_legacy_request_budgets(relationships):
    new = DemoBudgets(max_relationships=relationships)
    old = DemoBudgets.from_sealed({"max_relationships": relationships})
    assert new.capture_tile_limit == 512 and new.capture_seconds == 45
    assert old.capture_tile_limit == 256
    for budget, expected in [(new, 548 * relationships + 1), (old, 292 * relationships + 1)]:
        assert budget.supplemental_request_limit == expected
        assert random_budgets(budget.model_dump(), 3, {})["supplemental_requests"] == expected
        staged = native.staged_package(
            True, True, True, network_service_limit=3, random_budget=budget.model_dump()
        )
        assert f"planner_requests>={expected}".encode() in staged["network-parent.nut"]


def test_legacy_staging_matches_consumed_frozen_source():
    metadata = json.loads((RUN / "PRELAUNCH.json").read_bytes())
    sealed = metadata["random_budget"]
    assert "capture_tile_limit" not in sealed
    with zipfile.ZipFile(RUN / "frozen-source.zip") as archive:
        source = archive.read("app/demo_random_native.py")
    namespace: dict[str, Any] = {"__name__": "retained_random_native"}
    exec(compile(source, "retained/demo_random_native.py", "exec"), namespace)
    base = native.staged_package(True, True, True, network_service_limit=3)
    assert stage_random(base, sealed) == namespace["stage_random"](base, sealed)


def test_stage_random_refuses_unknown_seam_shape(tmp_path):
    """Anchored seams fail preparation loudly instead of shipping silently rewritten code."""
    base = native.staged_package(True, True, True, network_service_limit=3)
    budget = {"capture_tile_limit": 512, "max_relationships": 16}
    grown = dict(base)
    grown["delivery.nut"] = base["delivery.nut"] + b"/64"  # unexpected extra 64-map seam
    with pytest.raises(ValueError, match="STAGING_SEAM_DRIFT: delivery.nut seam /64"):
        stage_random(grown, budget)
    removed = dict(base)
    removed["network-parent.nut"] = base["network-parent.nut"].replace(b"/64", b"", 1)
    with pytest.raises(ValueError, match=r"seam /64 matched 7 times, expected 8"):
        stage_random(removed, budget)


def test_prepare_preflight_seals_explicit_capture_limits(tmp_path):
    budgets = DemoBudgets(max_relationships=2, capture_seconds=7)
    prepared = native.prepare(
        tmp_path / ("playable-demo-" + "d" * 32),
        demo=True,
        planner=True,
        network=True,
        scenario="high-budget-500k",
        random_world=RandomWorldSettings(seed=17).model_dump(),
        random_budget=budgets.model_dump(),
    )
    try:
        native.preflight(prepared)
        metadata = json.loads((prepared.directory / "PRELAUNCH.json").read_bytes())
        assert metadata["random_budget"]["capture_tile_limit"] == 512
        assert metadata["random_budget"]["capture_seconds"] == 7
        assert metadata["budgets"]["supplemental_requests"] == 1097
        assert not (prepared.directory / "CLAIM.json").exists()
    finally:
        prepared.spec.workspace.close()


def test_capture_timeout_is_explicit_without_connection(tmp_path):
    value = controlled_input()
    calls = []

    async def timeout(session, request, directory, response_type):
        calls.append(request.kind)
        raise TimeoutError("controlled deadline expiry")

    backend = SimpleNamespace(health=lambda: None, session=object())
    with pytest.raises(ValueError, match="CAPTURE_TIME_BUDGET"):
        asyncio.run(
            capture_planning_facts(
                backend,
                SimpleNamespace(directory=tmp_path),
                value.admitted.world,
                read_exchange=timeout,
                retain=False,
                relationship=(0, 1, 1),
                capture_budget=DemoBudgets(),
            )
        )
    assert calls == ["settings"]
    assert backend.planning_read_attempts == 1
    assert backend.planning_read_count == 0


def test_planning_reply_packet_and_tile_shape_bounds_unchanged():
    from app.simulation.openttd.freight_runtime_planning import PlanningRead

    request = PlanningRead(request_id="bound", kind="tile", arg=0, src=0, dst=1, cargo=1)
    payload = request.model_dump() | dict(type="planning_read_result", before=1, after=1)
    for size in (18, 20):
        with pytest.raises(ValueError, match="shape mismatch"):
            PlanningReadback.parse_for(
                request, json.dumps(payload | dict(data=[0] * size)).encode()
            )
    raw = json.dumps(payload | dict(data=[0] * 19)).encode()
    assert len(PlanningReadback.parse_for(request, raw).data) == 19
    with pytest.raises(ValueError, match="exceeds 512 bytes"):
        PlanningReadback.parse_for(request, raw + b" " * 513)
