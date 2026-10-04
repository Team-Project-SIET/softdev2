"""Regression coverage for canonical staging; no OpenTTD process is launched."""

import json
from hashlib import sha256
from pathlib import Path

import pytest

from app.experiments.plan_evaluation import PlanEvaluationInput
from app.experiments.plan_service import runtime_config
from app.planning.canonical import canonical_bytes, plan_hash
from app.planning.optimizer import optimize_candidate_network
from app.planning.transport import materialize_plan, transport_bytes
from tests.p07_proof_harness import authoritative_input, freeze_package, verify_frozen
from tests.test_planning_transport_live import WORLD_SOURCE

ATTEMPT1 = Path(__file__).parents[1] / "artifacts/planning/p07-proof-attempt1-20261004T075402Z"


def persisted_input():
    return (ATTEMPT1 / "plan-input.json").read_bytes()


def permuted_input():
    data = json.loads(persisted_input())
    data["scenario"]["world_manifest"]["resolved_sites"].reverse()
    return json.dumps(data).encode()


def stage(raw, directory):
    value = authoritative_input(raw)
    directory.mkdir(mode=0o700)
    package = materialize_plan(
        value.plan, value.scenario, plan_hash(value.plan), directory, WORLD_SOURCE, value.bindings
    )
    return value, package, freeze_package(value, package)


def test_staging_follows_canonical_reparse(tmp_path):
    value, package, frozen = stage(permuted_input(), tmp_path / "stage")
    assert value == PlanEvaluationInput.model_validate_json(canonical_bytes(value))
    assert package.module_path.read_bytes() == transport_bytes(
        value.plan, value.scenario, plan_hash(value.plan), value.bindings
    )
    assert runtime_config(value) == runtime_config(authoritative_input(frozen.input_bytes))


def test_equivalent_site_permutations_stage_identical_packages(tmp_path):
    first, _, a = stage(persisted_input(), tmp_path / "a")
    second, _, b = stage(permuted_input(), tmp_path / "b")
    assert first == second
    assert a == b


def test_frozen_package_matches_independent_disk_read_and_launch_path(tmp_path):
    value, package, frozen = stage(persisted_input(), tmp_path / "stage")
    launch_package = tmp_path / "launched" / "P03ThinExecutor"
    import shutil

    shutil.copytree(package.ai_directory, launch_package)
    verify_frozen(value, launch_package, frozen)
    assert frozen.module_sha256 == sha256((launch_package / "plan.nut").read_bytes()).hexdigest()
    assert (
        frozen.package_sha256
        == sha256(
            b"".join(
                (launch_package / n).read_bytes() for n in ("info.nut", "main.nut", "plan.nut")
            )
        ).hexdigest()
    )


@pytest.mark.parametrize("name", ["plan.nut", "main.nut", "info.nut"])
def test_package_mutation_after_freeze_rejected(tmp_path, name):
    value, package, frozen = stage(persisted_input(), tmp_path / "stage")
    file = package.ai_directory / name
    file.chmod(0o600)
    file.write_bytes(file.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="differs from frozen"):
        verify_frozen(value, package.ai_directory, frozen)


def test_equivalent_object_reordering_after_freeze_rejected(tmp_path):
    value, package, frozen = stage(persisted_input(), tmp_path / "stage")
    manifest = value.scenario.world_manifest.model_copy(
        update={"resolved_sites": tuple(reversed(value.scenario.world_manifest.resolved_sites))}
    )
    reordered = value.model_copy(
        update={"scenario": value.scenario.model_copy(update={"world_manifest": manifest})}
    )
    assert canonical_bytes(reordered) == frozen.input_bytes
    with pytest.raises(ValueError, match="authoritative canonical"):
        verify_frozen(reordered, package.ai_directory, frozen)


def test_input_mutation_after_freeze_rejected(tmp_path):
    value, package, frozen = stage(persisted_input(), tmp_path / "stage")
    changed = value.model_copy(
        update={
            "estimated": value.estimated.model_copy(update={"predicted_delivered_cargo_units": 99})
        }
    )
    with pytest.raises(ValueError, match="input changed after freeze"):
        verify_frozen(changed, package.ai_directory, frozen)


def test_freeze_rejects_module_generated_from_raw_order(tmp_path):
    raw = PlanEvaluationInput.model_validate_json(permuted_input())
    authoritative = authoritative_input(raw)
    directory = tmp_path / "stage"
    directory.mkdir(mode=0o700)
    package = materialize_plan(
        raw.plan, raw.scenario, plan_hash(raw.plan), directory, WORLD_SOURCE, raw.bindings
    )
    with pytest.raises(ValueError, match="different input graph"):
        freeze_package(authoritative, package)


def test_p05_plan_identity_deterministic_for_equivalent_canonical_inputs():
    a = authoritative_input(persisted_input())
    b = authoritative_input(permuted_input())
    first = optimize_candidate_network(a.scenario)
    second = optimize_candidate_network(b.scenario)
    assert canonical_bytes(first.plan) == canonical_bytes(second.plan) == canonical_bytes(a.plan)
    assert (
        plan_hash(first.plan) == "6e213478cb338b8e8cd9f5b47bc3e13b1f05331addf481cd9dba26376e376d4b"
    )


def test_semantic_stop_and_construction_action_order_preserved():
    before = PlanEvaluationInput.model_validate_json(persisted_input())
    after = authoritative_input(before)
    assert before.plan.infrastructure.actions == after.plan.infrastructure.actions
    assert before.plan.routes == after.plan.routes


def test_harness_fix_leaves_production_source_untouched():
    freeze = json.loads((ATTEMPT1 / "prelaunch-source-freeze.json").read_bytes())
    for name, expected in freeze["source_sha256"].items():
        path = Path(name)
        if "/app/" in name or "/alembic/" in name:
            assert sha256(path.read_bytes()).hexdigest() == expected, name


def test_driver_rejects_missing_controlled_suite(tmp_path):
    from tests import p07_real_proof as driver

    report = tmp_path / "empty.xml"
    report.write_text("<testsuites />")
    with pytest.raises(ValueError, match="missing controlled test suite"):
        driver.controlled_summary(report)


def test_driver_observer_forwards_keyword_stop(monkeypatch):
    import asyncio

    from app.simulation.openttd.admin_observer import (
        AdminObserver,
        ExpectedServerIdentity,
        ObserverHealth,
        ObserverState,
    )
    from tests import p07_real_proof as driver

    stop_event = asyncio.Event()
    recorded = []
    forwarded = []

    async def original(self, emit, *, stop=None):
        assert stop is stop_event
        await emit(ObserverHealth(ObserverState.STOPPED))

    monkeypatch.setattr(AdminObserver, "run", original)
    observer = driver.observer_type(recorded.append)(
        "127.0.0.1",
        39800,
        "unused",
        "proof",
        "1",
        ExpectedServerIdentity("13.4", 17, "", 256, 256, 0),
    )
    asyncio.run(observer.run(forwarded.append, stop=stop_event))
    assert recorded == forwarded == [ObserverHealth(ObserverState.STOPPED)]


def test_driver_spawn_wrapper_preserves_keyword_arguments():
    import asyncio
    import sys

    from tests import p07_real_proof as driver

    events = []

    async def spawn(program: str, *, label: str) -> asyncio.subprocess.Process:
        assert label == "controlled-python"
        return await asyncio.create_subprocess_exec(program, "-c", "pass")

    wrapped = driver.record_processes(
        spawn,
        lambda args: events.append("before"),
        lambda child, args: events.append("after"),
    )

    async def run():
        child = await wrapped(sys.executable, label="controlled-python")
        assert await child.wait() == 0

    asyncio.run(run())
    assert events == ["before", "after"]


def test_driver_rejects_absent_artifact(tmp_path):
    from tests import p07_real_proof as driver

    with pytest.raises(ValueError, match="missing or unsafe proof artifact"):
        driver.digest(tmp_path / "absent.json")
