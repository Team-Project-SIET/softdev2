"""Offline regression for the retained random smoke launch boundary."""

import ast
import copy
import json
from pathlib import Path
from typing import Any

import pytest

from app.demo_smoke_preflight import require_independent_preflight

REVIEW = Path("artifacts/demos/random-smoke-review-20401e97d89d49afb0937c16df516418")
HARNESS = Path("examples/openttd-demo/random-smoke-harness.py")


def verdict():
    return json.loads((REVIEW / "independent-preflight.json").read_bytes())


def gate(value):
    original = verdict()
    require_independent_preflight(
        value,
        frozen_inputs_sha256=original["frozen_inputs_sha256"],
        prelaunch_sha256=original["prelaunch_sha256"],
    )


def test_producer_consumer_correspondence():
    gate(verdict())
    assert "status" not in verdict()


@pytest.mark.parametrize(
    "change",
    [
        {"overall": "FAIL"},
        {"overall": None},
        {"overall": True},
        {"overall": "UNKNOWN"},
        {"schema": "v2"},
        {"checks": {}},
        {"native_launches": 1},
        {"admin_connections": True},
        {"classification": "NATIVE"},
        {"prelaunch_sha256": "0" * 64},
        {"frozen_inputs_sha256": "0" * 64},
    ],
)
def test_reject_invalid_or_failed(change):
    with pytest.raises((ValueError, RuntimeError)):
        gate(verdict() | change)


def test_missing_verdict():
    value = verdict()
    del value["overall"]
    with pytest.raises(ValueError):
        gate(value)


@pytest.mark.parametrize("value", [None, [], "PASS", 1])
def test_malformed(value):
    with pytest.raises(ValueError):
        gate(value)


def test_contradictory_check():
    value = copy.deepcopy(verdict())
    value["checks"]["runtime_and_assets"]["status"] = "FAIL"
    with pytest.raises(ValueError):
        gate(value)


@pytest.mark.parametrize("passed", [True, False])
def test_actual_harness_stops_before_authorization_and_launch(passed):
    # Execute the actual consumer call only; native imports/callbacks are unreachable.
    tree = ast.parse(HARNESS.read_text())
    node = next(
        n
        for n in tree.body
        if isinstance(n, ast.Expr)
        and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Name)
        and n.value.func.id == "require_independent_preflight"
    )
    boundary = next(i for i, n in enumerate(tree.body) if n is node)
    claim = next(i for i, n in enumerate(tree.body) if isinstance(n, ast.With))
    assert boundary < claim
    value = verdict() | {"overall": "PASS" if passed else "FAIL"}
    namespace = dict(
        require_independent_preflight=require_independent_preflight,
        independent=value,
        review=REVIEW,
        sha256=lambda _: verdict()["frozen_inputs_sha256"],
        intent={"prelaunch_sha256": verdict()["prelaunch_sha256"]},
    )
    code = compile(ast.Module(body=[node], type_ignores=[]), str(HARNESS), "exec")
    if passed:
        exec(code, namespace)
    else:
        with pytest.raises(RuntimeError, match="did not pass"):
            exec(code, namespace)


@pytest.mark.parametrize("fail_preflight", [False, True])
def test_full_offline_prelaunch_prefix(tmp_path, monkeypatch, fail_preflight):
    import socket
    import sys

    from app.demo_random import DemoBudgets, RandomWorldSettings
    from app.simulation.openttd.proof import freight_delivery as native
    from app.simulation.openttd.proof.harness import sha256

    def forbidden(*args, **kwargs):
        pytest.fail("native launch or Admin connection forbidden")

    monkeypatch.setattr(native.DemoBackend, "launch", forbidden)
    monkeypatch.setattr(native.DeliverySession, "connect_secure", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    root = tmp_path / ("playable-demo-" + "b" * 32)
    prepared = native.prepare(
        root,
        demo=True,
        planner=True,
        network=True,
        scenario="high-budget-500k",
        random_world=RandomWorldSettings(seed=17).model_dump(),
        random_budget=DemoBudgets().model_dump(),
    )
    try:
        review = tmp_path / "review"
        review.mkdir()
        intent = dict(
            run_directory=str(root),
            view_seconds=120,
            extra_source_hashes={},
            prelaunch_sha256=sha256(root / "PRELAUNCH.json"),
        )
        (review / "frozen-inputs.json").write_text(json.dumps(intent))
        digest = sha256(review / "frozen-inputs.json")
        (review / "frozen-inputs.sha256").write_text(digest)
        (review / "launch-harness.sha256").write_text(sha256(HARNESS))
        value = verdict() | dict(
            frozen_inputs_sha256=digest, prelaunch_sha256=intent["prelaunch_sha256"]
        )
        (review / "independent-preflight.json").write_text(json.dumps(value))
        monkeypatch.setattr(sys, "argv", [str(HARNESS), str(review)])
        monkeypatch.setenv("SDL_VIDEODRIVER", "x11")
        original = native.preflight

        def checked(p):
            original(p)
            if fail_preflight:
                raise ValueError("controlled failed runtime preflight")

        monkeypatch.setattr(native, "preflight", checked)
        tree = ast.parse(HARNESS.read_text())
        claim = next(i for i, n in enumerate(tree.body) if isinstance(n, ast.With))
        code = compile(ast.Module(body=tree.body[:claim], type_ignores=[]), str(HARNESS), "exec")
        namespace: dict[str, Any] = {"__file__": str(HARNESS)}
        if fail_preflight:
            with pytest.raises(ValueError, match="controlled failed runtime preflight"):
                exec(code, namespace)
            assert "viewer" not in namespace
        else:
            exec(code, namespace)
            assert namespace["viewer"].process is None
        assert not (review / "launch-authorization-consumed.json").exists()
        assert not (root / "CLAIM.json").exists()
    finally:
        prepared.spec.workspace.close()
