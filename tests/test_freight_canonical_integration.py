"""Integration of the concrete qualification callbacks; zero native processes."""

import asyncio
import copy
from types import SimpleNamespace

import pytest
from test_freight_canonical import observation, parse

from app.simulation.openttd import freight_canonical_dispatch, freight_canonical_runtime
from app.simulation.openttd.proof import canonical_fleet


def test_reload_purchase_uses_concrete_snapshot_verifier(tmp_path, monkeypatch):
    created = parse(observation())
    loaded = created.model_copy(update={"qualification_id": canonical_fleet.RELOAD})
    source = tmp_path / "source"
    source.mkdir()
    for service in range(3):
        (source / f"native-plan-{service}.json").write_text("{}")
    monkeypatch.setattr(canonical_fleet, "load_created", lambda _: created)
    monkeypatch.setattr(
        canonical_fleet,
        "DeliveryPlan",
        SimpleNamespace(model_validate_json=lambda _: SimpleNamespace(digest="a" * 64)),
    )

    async def saved(*args):
        (tmp_path / "purchase-readback.sav").write_bytes(b"controlled-native-save")

    async def raw_collector(*args, **kwargs):
        assert kwargs["require_restored"] is True
        assert kwargs["expected_vehicle_count"] == 3
        return dict(state=created.state.model_dump(mode="json"))

    async def qualify(*args, snapshot, **kwargs):
        assert await snapshot(None, 0, started=False) is True
        return {"controlled": True}

    monkeypatch.setattr(canonical_fleet, "protected_save", saved)
    monkeypatch.setattr(freight_canonical_runtime, "collect_raw_canonical", raw_collector)
    monkeypatch.setattr(freight_canonical_dispatch, "qualify_paused_purchase", qualify)
    asyncio.run(
        canonical_fleet.qualify_purchase(
            object(),
            SimpleNamespace(directory=tmp_path),
            object(),
            loaded,
            dict(
                canonical_directory=str(source),
                bridge_sha256="b" * 64,
                configuration_sha256="c" * 64,
            ),
        )
    )
    assert (tmp_path / "paused-purchase-qualification.json").is_file()


@pytest.mark.parametrize("arm", ["A", "B"])
def test_concrete_loaded_arm_snapshot_adapter(tmp_path, monkeypatch, arm):
    data = observation()
    data["state"]["map"]["service_plans"] = [str(i) * 64 for i in (1, 2, 3)]
    created = parse(data)
    loaded = created.model_copy(update={"qualification_id": "fresh-arm-" + arm})
    phases = []

    async def saved(backend, prepared, name):
        (prepared.directory / (name + ".sav")).write_bytes(b"native-like-snapshot")

    async def collect(session, directory, **kwargs):
        assert kwargs["require_restored"] is True
        assert kwargs["source_save_sha256"] == created.source_save_sha256
        assert kwargs["expected_vehicle_count"] == (4 if arm == "B" else 3)
        assert kwargs["snapshot_path"].is_file()
        state = copy.deepcopy(created.state.model_dump(mode="json"))
        state["cash"] -= 4429 if arm == "B" else 0
        for v in state["vehicles"]:
            v["stopped"] = len(phases) == 0
        phases.append("snapshot")
        return dict(state=state)

    async def dispatch(session, directory, canonical, current, **kwargs):
        assert canonical == current
        assert kwargs["service_plans"] == tuple(data["state"]["map"]["service_plans"])
        binding = dict(service=1, vehicle=4, purchase_capex=4429) if arm == "B" else None
        capex = 4429 if binding else 0
        assert await kwargs["snapshot"](binding, capex, started=False) is True
        assert await kwargs["snapshot"](binding, capex, started=True) is True
        assert await kwargs["unpause"]() == {"observed": "unpaused"}
        return dict(arm=arm, purchase_capex=capex)

    async def unpause(*args):
        phases.append("native-unpause-ack")
        return {"observed": "unpaused"}

    monkeypatch.setattr(canonical_fleet, "protected_save", saved)
    monkeypatch.setattr(freight_canonical_runtime, "collect_raw_canonical", collect)
    monkeypatch.setattr(freight_canonical_dispatch, "dispatch_common", dispatch)
    monkeypatch.setattr(freight_canonical_dispatch, "unpause_native", unpause)
    result = asyncio.run(
        freight_canonical_dispatch.dispatch_loaded_arm(
            object(),
            SimpleNamespace(directory=tmp_path),
            object(),
            created=created,
            loaded=loaded,
            arm=arm,
        )
    )
    assert result["arm"] == arm
    assert phases == ["snapshot", "snapshot", "native-unpause-ack"]
    assert (tmp_path / "canonical-dispatch.json").is_file()
