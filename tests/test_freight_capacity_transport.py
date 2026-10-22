"""Existing secure exchange and fourth-vehicle receipt orchestration, controlled only."""

import asyncio
import hashlib
import json
import struct
from types import SimpleNamespace

import pytest
from test_freight_capacity_execution import capacity_vm, plain

from app.simulation.openttd.freight_capacity_execution import CapacityReceipt, CapacityRequest
from app.simulation.openttd.freight_native_network import (
    execute_capacity_intervention,
    replay_capacity_intervention,
)
from app.simulation.openttd.gamescript_transport import SERVER_GAMESCRIPT, encode_gamescript
from app.simulation.openttd.proof.freight_delivery import exchange, network_budgets


def metadata(service=1):
    telemetry = dict(version=2, vehicle_count=4, max_tick_gap=1000)
    intervention = dict(version=1, service=service, max_cost=5000)
    return dict(
        capacity_telemetry=telemetry,
        capacity_intervention=intervention,
        budgets=network_budgets(
            3, 5, capacity_telemetry=telemetry, capacity_intervention=intervention
        ),
    )


def test_capacity_reply_uses_existing_exchange_and_native_size_bound(tmp_path):
    vm = capacity_vm()
    raw = json.dumps(plain(vm.get_roottable()["replies"][0])).encode()

    class Session:
        async def send(self, frame):
            self.sent = frame

        async def receive(self):
            return struct.pack("<HB", len(raw) + 4, SERVER_GAMESCRIPT) + raw + b"\0"

    q = CapacityRequest("add-1", 1, 5000)
    result = asyncio.run(exchange(Session(), q, tmp_path, response_type=CapacityReceipt))
    assert result.vehicle == 4 and result.purchase_capex == 4429
    assert (tmp_path / "add-1-request.json").read_bytes() == q.to_bytes()
    assert (tmp_path / "add-1-response.json").read_bytes() == raw


@pytest.mark.parametrize("service", [0, 1, 2])
def test_existing_network_helper_binds_and_replays_extra_once(tmp_path, monkeypatch, service):
    from app.simulation.openttd.proof import freight_delivery

    vm = capacity_vm(service)
    plans = [SimpleNamespace(digest="a" * 64, a=(0, 1, 2, 5, 10, 0, 20), f=(0, 0, 0, 0, 0, 20))] * 3
    receipts = [dict(route_id=f"route-{i}", vehicle=i + 1) for i in range(3)]
    frames = []

    async def retained_vm_exchange(session, q, directory, *, response_type):
        if q.read:
            vm.execute('q.type="capacity-read";q.request_id="capacity-read";b.Handle(q);')
        else:
            vm.execute('replies[0].request_id="capacity-add";')
        response = vm.get_roottable()["replies"][1 if q.read else 0]
        raw = json.dumps(plain(response)).encode()
        (directory / f"{q.request_id}-request.json").write_bytes(q.to_bytes())
        (directory / f"{q.request_id}-response.json").write_bytes(raw)
        frames.extend(
            [
                ["outbound", encode_gamescript(q.to_bytes()).hex()],
                [
                    "inbound",
                    (struct.pack("<HB", len(raw) + 4, SERVER_GAMESCRIPT) + raw + b"\0").hex(),
                ],
            ]
        )
        (directory / "frames.json").write_text(json.dumps(frames))
        return response_type.parse_for(q, raw)

    monkeypatch.setattr(freight_delivery, "exchange", retained_vm_exchange)
    result = dict(requests=65, mutations=30)
    m = metadata(service)
    prepared = SimpleNamespace(directory=tmp_path)
    augmented = asyncio.run(
        execute_capacity_intervention(prepared, object(), plans, receipts, m, result)
    )
    assert receipts[service].get("additional_vehicles") is None
    assert augmented[service]["additional_vehicles"] == [
        dict(service=service, vehicle=4, purchase_capex=4429)
    ]
    assert replay_capacity_intervention(tmp_path, plans, receipts, m) == augmented
    assert result == dict(requests=67, mutations=34)
    for broken in ([], frames + frames[:2], list(reversed(frames))):
        (tmp_path / "frames.json").write_text(json.dumps(broken))
        with pytest.raises(ValueError, match="secure capacity"):
            replay_capacity_intervention(tmp_path, plans, receipts, m)
    (tmp_path / "frames.json").write_text(json.dumps(frames))
    body = json.loads((tmp_path / "capacity-receipt.json").read_text())
    body["binding"]["service"] = (service + 1) % 3
    (tmp_path / "capacity-receipt.json").write_text(json.dumps(body))
    with pytest.raises(ValueError, match="receipt mismatch"):
        replay_capacity_intervention(tmp_path, plans, receipts, m)


def test_budget_requires_explicit_fourth_vehicle_and_telemetry():
    with pytest.raises(ValueError, match="explicit intervention"):
        network_budgets(3, 5, capacity_telemetry=dict(version=2, vehicle_count=4))
    with pytest.raises(ValueError, match="four-vehicle telemetry"):
        network_budgets(3, 5, capacity_intervention=dict(version=1, service=2, max_cost=5000))


def test_partial_intervention_retains_both_reads_without_complete_receipt(tmp_path, monkeypatch):
    from app.simulation.openttd.proof import freight_delivery

    vm = capacity_vm(failure=2)
    seen = []

    async def partial_exchange(session, q, directory, *, response_type):
        seen.append(q.request_id)
        if q.read:
            vm.execute('q.type="capacity-read";q.request_id="capacity-read";b.Handle(q);')
        else:
            vm.execute('replies[0].request_id="capacity-add";')
        raw = json.dumps(plain(vm.get_roottable()["replies"][1 if q.read else 0])).encode()
        (directory / f"{q.request_id}-request.json").write_bytes(q.to_bytes())
        (directory / f"{q.request_id}-response.json").write_bytes(raw)
        return response_type.parse_for(q, raw)

    monkeypatch.setattr(freight_delivery, "exchange", partial_exchange)
    plans = [SimpleNamespace()] * 3
    receipts = [dict(vehicle=i + 1) for i in range(3)]
    with pytest.raises(ValueError, match="partial capacity"):
        asyncio.run(
            execute_capacity_intervention(
                SimpleNamespace(directory=tmp_path),
                object(),
                plans,
                receipts,
                metadata(),
                dict(requests=65, mutations=30),
            )
        )
    assert seen == ["capacity-add", "capacity-read"]
    assert json.loads((tmp_path / "capacity-read-response.json").read_bytes())["vehicle"] == 4
    assert not (tmp_path / "capacity-receipt.json").exists()


@pytest.mark.parametrize("target", [None, 1, 2])
def test_preflight_rejects_every_matched_arm_before_backend_or_claim(tmp_path, monkeypatch, target):
    from app.simulation.openttd.proof import freight_delivery

    m = metadata(1 if target is None else target)
    if target is None:
        m.pop("capacity_intervention")
        m["capacity_telemetry"]["vehicle_count"] = 3
    m.update(
        schema="first-freight-delivery-prelaunch-v1",
        attempt=1,
        frozen={},
        network=True,
        network_service_limit=3,
        continuous_years=5,
    )
    m["budgets"] = network_budgets(
        3,
        5,
        capacity_telemetry=m["capacity_telemetry"],
        capacity_intervention=m.get("capacity_intervention"),
    )
    raw = json.dumps(m).encode()
    (tmp_path / "PRELAUNCH.json").write_bytes(raw)
    (tmp_path / "PRELAUNCH.sha256").write_text(hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(freight_delivery, "attempt_number", lambda path: 1)

    def forbidden(*args, **kwargs):
        pytest.fail("blocked matched arm reached backend")

    monkeypatch.setattr(freight_delivery, "backend_for", forbidden)
    with pytest.raises(ValueError, match="canonical paused post-construction"):
        freight_delivery.preflight(SimpleNamespace(directory=tmp_path))
    assert not (tmp_path / "CLAIM.json").exists()
