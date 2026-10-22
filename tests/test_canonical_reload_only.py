"""Exercise the complete owned reload orchestration without native I/O."""

import asyncio
import copy
import json
import shutil
from types import SimpleNamespace

import pytest
from test_freight_canonical import observation, parse
from test_freight_canonical_dispatch import receipt

from app.simulation.openttd import freight_canonical_dispatch as dispatch
from app.simulation.openttd import freight_canonical_runtime as runtime
from app.simulation.openttd.proof import canonical_fleet as driver


@pytest.mark.parametrize(
    "failure",
    [None, "correspondence", "heartbeat", "binding", "finance", "restored", "evidence", "cleanup"],
)
def test_reload_run_never_purchases_dispatches_or_unpauses(monkeypatch, tmp_path, failure):
    calls = []
    root = tmp_path / "isolated"
    logs = root / "logs"
    logs.mkdir(parents=True)
    key = root / ".admin-secret"
    key.write_bytes(b"offline-test-key")
    prepared = SimpleNamespace(
        directory=tmp_path,
        key_path=key,
        endpoints=(1, 2),
        spec=SimpleNamespace(
            workspace=SimpleNamespace(root=root, logs=logs, close=lambda: shutil.rmtree(root))
        ),
    )
    (tmp_path / "PRELAUNCH.json").write_text("{}")
    canonical = tmp_path / "source"
    canonical.mkdir()
    created = parse(observation())
    unchanged = copy.deepcopy(created.model_dump(mode="json"))
    loaded = created.model_copy(update={"qualification_id": driver.RELOAD})
    metadata = dict(
        qualification_id=driver.RELOAD,
        canonical_directory=str(canonical),
        bridge_sha256=created.bridge_sha256,
        configuration_sha256=created.configuration_sha256,
        execution_contract=driver.RELOAD_ONLY_CONTRACT,
        budgets={"total_seconds": 2},
    )

    class Backend:
        process = None

        async def launch(self, value):
            calls.append("launch")

        async def cleanup(self, value):
            calls.append("cleanup")
            return dict(reaped=failure != "cleanup", cleanup_error=[], sockets_closed=True)

    class Session:
        state = driver.AuthState.ACTIVE
        welcome = None
        protocol = object()

        async def authenticate(self, *args, **kwargs):
            calls.append("authenticate")

    from dataclasses import make_dataclass

    welcome = make_dataclass("Welcome", ["revision", "seed", "width", "height"])
    Session.welcome = welcome("15.3", 42, 64, 64)
    session = Session()

    async def connect(*args, **kwargs):
        calls.append("connect")
        return session

    async def no_op(*args, **kwargs):
        pass

    async def context(*args):
        calls.append("road-context")

    async def save(*args):
        calls.append("save")

    async def collect(*args, **kwargs):
        calls.append("collect")
        if failure == "correspondence":
            raise ValueError("canonical correspondence mismatch: state")
        return loaded

    async def boundary(*args):
        calls.append(args[-1])
        return receipt(
            tick=10 if args[-1] == "reload-before" or failure == "heartbeat" else 11,
            economy_date=created.state.economy_date,
            cash=created.state.cash - (failure == "finance"),
            restored=failure != "restored",
            loan=created.state.loan,
            originals=[
                [v.service, v.vehicle + (failure == "binding"), v.tile, 0, 0, 2]
                for v in created.state.vehicles
            ],
        )

    def forbidden(*args, **kwargs):
        pytest.fail("reload-only reached purchase, dispatch, mutation or unpause")

    monkeypatch.setattr(
        driver.freight,
        "ScenarioPlanningAccounting",
        lambda _: SimpleNamespace(observe=lambda *args: None, enter=lambda *args: None),
    )
    monkeypatch.setattr(driver, "CanonicalBackend", lambda **kwargs: Backend())
    monkeypatch.setattr(driver, "preflight", lambda _: metadata)
    monkeypatch.setattr(driver, "wait_log", no_op)
    monkeypatch.setattr(driver, "console", forbidden)
    monkeypatch.setattr(driver, "qualify_purchase", forbidden)
    monkeypatch.setattr(dispatch, "qualify_paused_purchase", forbidden)
    monkeypatch.setattr(dispatch, "dispatch_common", forbidden)
    monkeypatch.setattr(dispatch, "unpause_native", forbidden)
    monkeypatch.setattr(driver, "acquire", forbidden)
    monkeypatch.setattr(driver, "establish_reload_context", context)
    monkeypatch.setattr(driver, "protected_save", save)
    monkeypatch.setattr(driver, "load_created", lambda _: created)
    monkeypatch.setattr(driver, "verify_cleanup_endpoints", lambda *args: {})
    monkeypatch.setattr(driver.AuthorizedKey, "from_bytes", lambda _: None)
    monkeypatch.setattr(driver.freight.PlannerDeliverySession, "connect_secure", connect)
    monkeypatch.setattr(
        driver, "GameScriptTransport", lambda *args: SimpleNamespace(subscribe=no_op)
    )
    monkeypatch.setattr(runtime, "verify_reloaded", collect)
    monkeypatch.setattr(dispatch, "read_boundary", boundary)
    if failure == "evidence":
        (tmp_path / "frames.json").write_text("existing evidence")
    result = asyncio.run(driver.run(prepared, authorize_one_launch=True))
    assert calls[:4] == ["launch", "connect", "authenticate", "road-context"]
    assert calls.count("launch") == calls.count("connect") == calls.count("cleanup") == 1
    assert result["mutations"] == 0
    assert created.model_dump(mode="json") == unchanged
    assert (tmp_path / "artifact-manifest.sha256").exists()
    assert json.loads((tmp_path / "cleanup.json").read_bytes())["sockets_closed"]
    if failure is None:
        assert result["status"] == "CANONICAL_RELOAD_ONLY_VERIFIED"
        assert not root.exists()
        assert driver.load_created(canonical) == created
        assert (
            json.loads((tmp_path / "reload-correspondence.json").read_bytes())["execution_contract"]
            == driver.RELOAD_ONLY_CONTRACT
        )
        assert json.loads((tmp_path / "reload-observation.json").read_bytes()) == loaded.model_dump(
            mode="json"
        )
    elif failure in ("correspondence", "heartbeat", "binding", "finance", "restored"):
        assert result["status"] == "FAILED"
        assert not (tmp_path / "reload-correspondence.json").exists()
        if failure == "correspondence":
            assert "reload-after" not in calls
            assert "correspondence mismatch" in result["error"]
    else:
        assert result["status"] == (
            "FAILED_EVIDENCE" if failure == "evidence" else "FAILED_CLEANUP"
        )


@pytest.mark.parametrize("change", ["missing", "purchase", "dispatch", "unpause", "mode", "extra"])
def test_preflight_rejects_non_reload_only_contract_before_runtime(tmp_path, monkeypatch, change):
    directory = tmp_path / driver.RELOAD
    directory.mkdir()
    contract = dict(driver.RELOAD_ONLY_CONTRACT)
    if change == "mode":
        contract["mode"] = "reload-and-purchase"
    elif change == "extra":
        contract["allow_purchase"] = True
    elif change != "missing":
        contract[change] = True
    metadata = dict(
        qualification_id=driver.RELOAD,
        schema=driver.SCHEMA,
        frozen={},
        bridge_sha256="bridge",
        configuration_sha256="config",
    )
    if change != "missing":
        metadata["execution_contract"] = contract
    path = directory / "PRELAUNCH.json"
    path.write_text(json.dumps(metadata))
    (directory / "PRELAUNCH.sha256").write_text(driver.sha256(path))
    monkeypatch.setattr(driver, "package_bytes", lambda: {})
    monkeypatch.setattr(driver, "bridge_digest", lambda _: "bridge")
    monkeypatch.setattr(driver, "configuration_digest", lambda _: "config")

    def forbidden(*args, **kwargs):
        pytest.fail("invalid contract reached source loading or native runtime")

    monkeypatch.setattr(driver, "verify_created_source", forbidden)
    monkeypatch.setattr(driver, "CanonicalBackend", forbidden)
    prepared = SimpleNamespace(
        directory=directory,
        spec=SimpleNamespace(workspace=SimpleNamespace(config=None)),
    )
    with pytest.raises(ValueError, match="reload-only execution contract"):
        driver.preflight(prepared)
    assert not (directory / "CLAIM.json").exists()
