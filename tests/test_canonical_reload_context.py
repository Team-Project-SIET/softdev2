"""Paused reload establishes process-local API context without changing the save."""

import asyncio
from types import SimpleNamespace

import pytest

from app.simulation.openttd.freight_delivery import DeliveryPlan, DeliveryReadback
from app.simulation.openttd.proof import canonical_fleet as driver


@pytest.fixture
def context(tmp_path, monkeypatch):
    plan = DeliveryPlan(
        prelaunch_digest="a" * 64,
        source_save_digest="b" * 64,
        admission_digest="c" * 64,
        a=(1, 2, 0, 5, 10, 11, 20, 21, 30, 31),
        f=(0, 0, 0, 0, 100, 20, 100, 1),
    )
    (tmp_path / "native-plan-0.json").write_text(plan.model_dump_json())
    vehicle = SimpleNamespace(
        service=0,
        vehicle=4,
        owner=0,
        engine=5,
        capacity=20,
        tile=30,
        orders=[SimpleNamespace(destination=10), SimpleNamespace(destination=20)],
    )
    state = SimpleNamespace(vehicles=[vehicle], economy_date=712297, cash=471157)
    monkeypatch.setattr(driver, "load_created", lambda path: SimpleNamespace(state=state))
    s = [0] * 30
    for index, value in {
        1: 712297,
        2: 1,
        3: 471157,
        4: 4,
        5: 0,
        6: 5,
        7: 20,
        8: 30,
        12: 2,
        13: 10,
        14: 20,
        22: 10,
        28: 1,
        29: 1,
    }.items():
        s[index] = value
    read = DeliveryReadback(
        protocol=1,
        op="read",
        request_id="activate-reload-context",
        plan=plan.digest,
        arg=0,
        max_cost=100000,
        status="READ",
        a=plan.a,
        f=plan.f,
        s=tuple(s),
    )
    return tmp_path, state, read


def test_context_uses_correlated_read_without_world_mutation(context, monkeypatch):
    path, _, read = context
    calls = []

    async def exchange(session, request, directory):
        calls.append((session, request, directory))
        return read

    monkeypatch.setattr(driver.freight, "exchange", exchange)
    assert asyncio.run(driver.establish_reload_context("secure", path, path)) == read
    assert len(calls) == 1
    session, request, directory = calls[0]
    assert session == "secure" and directory == path
    assert request.op == "read" and request.arg == 0
    assert request.request_id == "activate-reload-context" and request.plan == read.plan
    assert list(path.iterdir()) == [path / "native-plan-0.json"]


@pytest.mark.parametrize(
    "index,value",
    [
        (1, 712298),
        (2, 0),
        (3, 471156),
        (4, 5),
        (5, 1),
        (6, 6),
        (7, 0),
        (8, 31),
        (10, 1),
        (11, 1),
        (12, 1),
        (13, 11),
        (14, 21),
        (18, 1),
        (22, 9),
        (28, 0),
        (29, 0),
    ],
)
def test_context_rejects_wrong_road_type_or_native_state(context, monkeypatch, index, value):
    path, _, read = context
    s = list(read.s)
    s[index] = value

    async def exchange(*args):
        return read.model_copy(update={"s": tuple(s)})

    monkeypatch.setattr(driver.freight, "exchange", exchange)
    with pytest.raises(ValueError, match="native road context or sealed service"):
        asyncio.run(driver.establish_reload_context(None, path, path))


@pytest.mark.parametrize("status", ["UNSUPPORTED_ROAD_TYPE", "OUT_OF_ORDER"])
def test_context_preserves_explicit_packaged_rejection(context, monkeypatch, status):
    path, _, read = context

    async def exchange(*args):
        return read.model_copy(update={"status": status})

    monkeypatch.setattr(driver.freight, "exchange", exchange)
    with pytest.raises(ValueError, match="native road context"):
        asyncio.run(driver.establish_reload_context(None, path, path))


def test_context_rejects_inconsistent_source_before_request(context, monkeypatch):
    path, state, _ = context
    state.vehicles[0].tile = 31

    async def forbidden(*args):
        pytest.fail("invalid source must fail before native read")

    monkeypatch.setattr(driver.freight, "exchange", forbidden)
    with pytest.raises(ValueError, match="source service binding"):
        asyncio.run(driver.establish_reload_context(None, path, path))


@pytest.mark.parametrize("identity", ["canonical-fleet-reload-q1", "canonical-fleet-reload-q2"])
def test_previous_reload_identities_rejected_before_workspace_creation(
    tmp_path, monkeypatch, identity
):
    def forbidden(*args, **kwargs):
        pytest.fail("consumed reload identity must be rejected before preparation")

    monkeypatch.setattr(driver.RuntimeWorkspace, "create", forbidden)
    directory = tmp_path / identity
    with pytest.raises(ValueError, match="identity"):
        driver.prepare(directory, stage=identity, canonical=tmp_path / "source")
    assert not directory.exists()
