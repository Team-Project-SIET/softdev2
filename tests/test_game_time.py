import json

import pytest

from app.experiments.game_time import GameTimeMetrics, network_game_time, service_game_time


def test_elapsed_uses_only_economy_dates():
    m = GameTimeMetrics(
        simulation_start_date=100,
        final_cargo_delivery_date=106,
        elapsed_script_ticks=500,
        elapsed_wall_clock_seconds=3,
    )
    assert m.total_elapsed_economy_days == 6
    assert GameTimeMetrics(final_cargo_delivery_date=106).total_elapsed_economy_days is None
    with pytest.raises(ValueError, match="requires start"):
        GameTimeMetrics(total_elapsed_economy_days=0)
    with pytest.raises(ValueError, match="mismatch"):
        GameTimeMetrics(
            simulation_start_date=100, final_cargo_delivery_date=106, total_elapsed_economy_days=500
        )


def test_historical_snapshot_bounds_pickup_and_records_delivery(tmp_path):
    for stage, day, accepted in (("read-9", 101, 0), ("observe-1", 103, 0), ("finish", 109, 108)):
        state = [0] * 30
        state[1], state[21] = day, accepted
        (tmp_path / f"s0-{stage}-response.json").write_text(json.dumps({"s": state}))
    m = service_game_time(tmp_path, 0, {})
    assert m.construction_observed_by_date == 101
    assert m.construction_completion_date is None
    assert m.pickup_observed_by_date == 103
    assert m.first_cargo_pickup_date is None
    assert m.final_cargo_delivery_date == 108
    assert m.total_elapsed_economy_days is None
    assert network_game_time((m, m, m)).final_cargo_delivery_date == 108
    assert network_game_time((m, GameTimeMetrics())).final_cargo_delivery_date is None


def test_future_receipt_readbacks_and_three_service_aggregation(tmp_path):
    from app.simulation.openttd.freight_native_network import aggregate_game_time, receipt_game_time

    receipts = []
    for index in range(3):
        for stage, day, accepted in (
            ("read-9", 101 + index * 10, 0),
            ("observe-1", 103 + index * 10, 0),
            ("finish", 109 + index * 10, 108 + index * 10),
        ):
            state = [0] * 30
            state[1], state[21] = day, accepted
            (tmp_path / f"s{index}-{stage}-response.json").write_text(json.dumps({"s": state}))
        receipts.append({"game_time": receipt_game_time(tmp_path, index)})
    result = GameTimeMetrics.model_validate_json(json.dumps(aggregate_game_time(receipts)))
    assert result.final_cargo_delivery_date == 128
    assert result.construction_observed_by_date == 121
    assert result.pickup_observed_by_date == 103
    assert result.total_elapsed_economy_days is None
    assert result.elapsed_calendar_days is None


def test_receipt_json_lists_and_known_network_dates(tmp_path):
    m = service_game_time(
        tmp_path,
        0,
        {
            "game_time": {
                "simulation_start_date": 100,
                "planning_completion_date": 101,
                "final_cargo_delivery_date": 108,
                "evidence_refs": ["retained.json"],
            }
        },
    )
    assert m.evidence_refs == ("retained.json",)
    aggregate = network_game_time((m, m, m))
    assert aggregate.total_elapsed_economy_days == 8
    assert aggregate.planning_completion_date == 101


def test_future_native_start_and_construction_markers_replay(tmp_path):
    from pathlib import Path

    from app.simulation.openttd.freight_delivery import DeliveryPlan
    from app.simulation.openttd.freight_native_network import receipt_game_time

    source = (
        Path(__file__).resolve().parents[1]
        / "artifacts/runtime/openttd-15.3-first-freight-delivery-attempt14/native-plan-0.json"
    )
    if not source.exists():
        pytest.skip("optional retained plan fixture unavailable")
    plan_bytes = source.read_bytes()
    (tmp_path / "native-plan-0.json").write_bytes(plan_bytes)
    digest = DeliveryPlan.model_validate_json(plan_bytes).digest
    for stage, day, accepted, tick in (
        ("read-9", 102, 0, 200),
        ("observe-1", 105, 0, 300),
        ("finish", 109, 108, 500),
        ("select", 101, 0, 150),
    ):
        state = [0] * 30
        state[0], state[1], state[21] = tick, day, accepted
        name = "select-0-response.json" if stage == "select" else f"s0-{stage}-response.json"
        (tmp_path / name).write_text(json.dumps({"s": state}))
    log = (
        f"FREIGHT_GAME_TIME_START date=100 tick=100\n"
        f"FREIGHT_GAME_TIME_CONSTRUCTION plan={digest} date=102 tick=190\n"
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    live_log = workspace / "stderr.log"
    live_log.write_text(log)
    assert not (tmp_path / "stderr.log").exists()
    live = receipt_game_time(tmp_path, 0, capture_start=True, log_path=live_log)
    assert live["total_elapsed_economy_days"] == 8
    assert "stderr.log" in live["evidence_refs"]
    (tmp_path / "stderr.log").write_text(log)
    assert live == receipt_game_time(tmp_path, 0, capture_start=True)
    m = GameTimeMetrics.model_validate_json(
        json.dumps(receipt_game_time(tmp_path, 0, capture_start=True))
    )
    assert m.simulation_start_date == 100
    assert m.start_basis == "bridge_start_before_world_preparation"
    assert m.planning_completion_date is None
    assert m.planning_completion_observed_by_date == 101
    assert m.construction_completion_date == 102
    assert m.total_elapsed_economy_days == 8
    assert m.elapsed_script_ticks is None
    (tmp_path / "stderr.log").write_text(log + log)
    with pytest.raises(ValueError, match="unique native"):
        receipt_game_time(tmp_path, 0, capture_start=True)


@pytest.mark.parametrize("version", [None, 1])
def test_supported_sealed_game_time_versions(version):
    from app.simulation.openttd.freight_native_network import validate_game_time_version

    assert validate_game_time_version({"game_time_metrics_version": version}) == version
    assert validate_game_time_version({}) is None


@pytest.mark.parametrize("version", [2, True, False, "1", 1.0])
def test_unsupported_sealed_game_time_versions_rejected(version):
    from app.simulation.openttd.freight_native_network import validate_game_time_version

    with pytest.raises(ValueError, match="unsupported game-time"):
        validate_game_time_version({"game_time_metrics_version": version})
