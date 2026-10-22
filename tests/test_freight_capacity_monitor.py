import asyncio
import json

import pytest

from app.simulation.openttd.freight_continuous import (
    collect_telemetry,
    monitoring_budgets,
    telemetry_options,
)
from app.simulation.openttd.freight_telemetry import SampleWindow, validate_bindings


def bindings():
    return [
        dict(service=0, vehicle=1),
        dict(service=1, vehicle=2),
        dict(service=2, vehicle=3),
        dict(service=1, vehicle=4),
    ]


def test_four_physical_vehicles_preserve_three_services_and_bounded_budget():
    values = validate_bindings(bindings())
    assert [b["service"] for b in values] == [0, 1, 2, 1]
    assert monitoring_budgets(4)["requests"] - monitoring_budgets()["requests"] == 14404
    options = dict(version=1, bindings=values, max_tick_gap=100)
    assert (
        telemetry_options(dict(capacity_telemetry=options), [dict(vehicle=n) for n in (1, 2, 3)])
        == options
    )
    values[-1]["vehicle"] = 2
    with pytest.raises(ValueError, match="coverage"):
        validate_bindings(values)


def test_same_session_raw_retention_vehicle_streams_and_gap(tmp_path, monkeypatch):
    asyncio.run(_same_session_raw_retention_vehicle_streams_and_gap(tmp_path, monkeypatch))


async def _same_session_raw_retention_vehicle_streams_and_gap(tmp_path, monkeypatch):
    from app.simulation.openttd.proof import freight_delivery

    seen = []
    session = object()

    async def fake_exchange(actual, q, directory, *, response_type):
        assert actual is session
        seen.append(q)
        tick = 1 if q.request_id.startswith("continuous-t0-") else 200
        raw = json.dumps(
            dict(
                protocol=1,
                type="continuous-telemetry-result",
                request_id=q.request_id,
                status="ok",
                service=q.service,
                vehicle=q.vehicle,
                tick=tick,
                economy_date=100,
                tile=10,
                state=1,
                speed=0,
                load=20,
                capacity=20,
                queue=1000,
                stopped_in_depot=False,
                at_station=True,
                source_tile=10,
                destination_tile=20,
                profit_this_year=-5,
                profit_last_year=0,
                running_cost_rate_per_year=421,
            )
        ).encode()
        (directory / f"{q.request_id}-request.json").write_bytes(q.to_bytes())
        (directory / f"{q.request_id}-response.json").write_bytes(raw)
        return response_type.parse_for(q, raw)

    monkeypatch.setattr(freight_delivery, "exchange", fake_exchange)
    options = dict(bindings=bindings(), max_tick_gap=10)
    windows = {b["vehicle"]: SampleWindow(10) for b in bindings()}
    result = dict(requests=0)
    for sequence in (0, 1):
        samples, digests = await collect_telemetry(
            session, tmp_path, options, sequence, result, dict(requests=8), windows
        )
        assert len(samples) == len(digests) == 4
        assert [s["service"] for s in samples] == [0, 1, 2, 1]
        assert samples[0]["profit_this_year"] == -5
    assert result["requests"] == 8
    assert len((tmp_path / "continuous-telemetry.jsonl").read_text().splitlines()) == 2
    assert windows[4].report()["transitions"][0]["labels"] == ["sampling_gap"]
    assert windows[4].report()["completed_delivery_frequency"] is None
    with pytest.raises(ValueError, match="request budget"):
        await collect_telemetry(session, tmp_path, options, 2, result, dict(requests=8), windows)


def test_telemetry_wire_requires_unique_raw_response_and_request_order(tmp_path):
    from app.simulation.openttd.admin_protocol import encode_admin_frame
    from app.simulation.openttd.freight_continuous import _verify_continuous_wire
    from app.simulation.openttd.freight_telemetry import telemetry_request
    from app.simulation.openttd.gamescript_transport import SERVER_GAMESCRIPT, encode_gamescript

    names = ["continuous-begin", "continuous-t0-v1"]
    frames = []
    for name in names:
        request = (
            json.dumps(dict(type="continuous-begin", request_id=name)).encode()
            if name == names[0]
            else telemetry_request(name, 0, 1)
        )
        response = json.dumps(dict(type="continuous-telemetry-result", request_id=name)).encode()
        (tmp_path / f"{name}-request.json").write_bytes(request)
        (tmp_path / f"{name}-response.json").write_bytes(response)
        frames.extend(
            [
                ["outbound", encode_gamescript(request).hex()],
                ["inbound", encode_admin_frame(SERVER_GAMESCRIPT, response + b"\0").hex()],
            ]
        )
    (tmp_path / "frames.json").write_text(json.dumps(frames))
    _verify_continuous_wire(
        tmp_path, names, complete=True, telemetry=dict(bindings=[dict(vehicle=1)])
    )
    (tmp_path / "continuous-t0-v1-response.json").write_bytes(b"{}")
    with pytest.raises(ValueError, match="unique secure exchange"):
        _verify_continuous_wire(
            tmp_path, names, complete=True, telemetry=dict(bindings=[dict(vehicle=1)])
        )


def test_v2_seals_count_and_derives_unknown_vehicle_id_from_receipts():
    receipts = [dict(vehicle=n) for n in (1, 2, 3)]
    receipts[1]["additional_vehicles"] = [dict(service=1, vehicle=99, purchase_capex=4429)]
    sealed = dict(version=2, vehicle_count=4, max_tick_gap=100)
    actual = telemetry_options(dict(capacity_telemetry=sealed), receipts)
    assert actual["bindings"][-1] == dict(service=1, vehicle=99)
    assert sealed == dict(version=2, vehicle_count=4, max_tick_gap=100)
    with pytest.raises(ValueError, match="fleet count"):
        telemetry_options(dict(capacity_telemetry=sealed), [dict(vehicle=n) for n in (1, 2, 3)])


def test_integrated_four_vehicle_monitor_and_raw_replay(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from test_freight_continuous import _controlled_exchange, _controlled_network

    from app.simulation.openttd import freight_continuous as continuous
    from app.simulation.openttd.admin_protocol import encode_admin_frame
    from app.simulation.openttd.gamescript_transport import SERVER_GAMESCRIPT, encode_gamescript
    from app.simulation.openttd.proof import freight_delivery

    plans, receipts = _controlled_network()
    normal, _ = _controlled_exchange(tmp_path, plans)
    augmented = [dict(r) for r in receipts]
    augmented[1]["additional_vehicles"] = [dict(service=1, vehicle=99, purchase_capex=4429)]
    metadata = dict(
        capacity_telemetry=dict(version=2, vehicle_count=4, max_tick_gap=100),
        capacity_intervention=dict(service=1),
        budgets=monitoring_budgets(4),
    )

    async def exchange(session, q, directory, **kwargs):
        if q.type != "continuous-telemetry":
            return await normal(session, q, directory, **kwargs)
        sequence = int(q.request_id.split("-")[1][1:])
        day = sequence * 30
        plan = plans[q.service]
        raw = json.dumps(
            dict(
                protocol=1,
                type="continuous-telemetry-result",
                request_id=q.request_id,
                status="ok",
                service=q.service,
                vehicle=q.vehicle,
                tick=day * 74,
                economy_date=720000 + day,
                tile=plan.a[4],
                state=1,
                speed=0,
                load=20,
                capacity=20,
                queue=1000,
                stopped_in_depot=False,
                at_station=True,
                source_tile=plan.a[4],
                destination_tile=plan.a[6],
            )
        ).encode()
        (directory / f"{q.request_id}-request.json").write_bytes(q.to_bytes())
        (directory / f"{q.request_id}-response.json").write_bytes(raw)
        session._frame_observer("outbound", encode_gamescript(q.to_bytes()))
        session._frame_observer("inbound", encode_admin_frame(SERVER_GAMESCRIPT, raw + b"\0"))
        return kwargs["response_type"].parse_for(q, raw)

    async def paced(seconds):
        pass

    monkeypatch.setattr(freight_delivery, "exchange", exchange)
    monkeypatch.setattr(continuous.asyncio, "sleep", paced)
    from app.simulation.openttd import freight_native_network

    monkeypatch.setattr(
        freight_native_network,
        "replay_capacity_intervention",
        lambda directory, plans, receipts, metadata: augmented,
    )
    logs = tmp_path / "logs"
    logs.mkdir()
    prepared = SimpleNamespace(
        directory=tmp_path, spec=SimpleNamespace(workspace=SimpleNamespace(logs=logs))
    )
    frames = []
    session = SimpleNamespace(_frame_observer=lambda d, f: frames.append((d, f.hex())))
    summary = asyncio.run(
        continuous.monitor_network(prepared, session, plans, augmented, metadata, dict(requests=68))
    )
    assert summary["financial_metrics"]["delivered_cargo"] == 108000
    assert summary["infrastructure_and_vehicle_capex_gbp"] == 4729
    (tmp_path / "PRELAUNCH.json").write_text(json.dumps(metadata))
    (tmp_path / "frames.json").write_text(json.dumps(frames))
    for n, plan in enumerate(plans):
        (tmp_path / f"native-plan-{n}.json").write_text(plan.model_dump_json())
        (tmp_path / f"service-receipt-{n}.json").write_text(json.dumps(receipts[n]))
    assert continuous.verify_continuous_evidence(tmp_path, _full=False)["complete"]
    path = tmp_path / "continuous-telemetry.jsonl"
    path.write_text(path.read_text().replace('"vehicle":99', '"vehicle":98'))
    with pytest.raises(ValueError, match="journal replay"):
        continuous.verify_continuous_evidence(tmp_path, _full=False)
