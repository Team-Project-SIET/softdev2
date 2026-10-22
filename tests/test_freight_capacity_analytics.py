"""Controlled P07 physical-fleet aggregation; no native improvement claim."""

import pytest

from app.experiments.freight_continuous_analytics import _metric


def fixture():
    return dict(
        services=[
            dict(
                service=i,
                route_id=f"S{i + 1}",
                vehicle=i,
                cargo_load=20,
                capacity=20,
                capacity_utilization=1.0,
                delivered=100,
                station_waiting_cargo=500,
            )
            for i in range(3)
        ],
        finance={},
        vehicle_telemetry=[dict(service=i, vehicle=i, load=20, capacity=20) for i in range(3)]
        + [dict(service=1, vehicle=99, load=0, capacity=20)],
    )


def test_capacity_uses_every_physical_vehicle_without_duplicating_service_counters():
    snapshot = fixture()
    assert _metric(snapshot, "network", "capacity_utilization") == 0.75
    assert _metric(snapshot, "S2", "capacity_utilization") == 0.5
    assert _metric(snapshot, "network", "delivered") == 300
    assert _metric(snapshot, "network", "station_waiting_cargo") == 1500


@pytest.mark.parametrize("field", ["load", "capacity"])
def test_missing_physical_measurement_remains_unknown(field):
    snapshot = fixture()
    snapshot["vehicle_telemetry"][-1][field] = None
    assert _metric(snapshot, "network", "capacity_utilization") is None
    assert _metric(snapshot, "S2", "capacity_utilization") is None


def test_historical_capacity_metric_unchanged():
    snapshot = fixture()
    del snapshot["vehicle_telemetry"]
    assert _metric(snapshot, "network", "capacity_utilization") == 1
    assert _metric(snapshot, "S2", "capacity_utilization") == 1


def test_opt_in_chart_labels_ratio_as_derived_and_preserves_historical_title(tmp_path):
    from test_freight_continuous_analytics import fixture as continuous_fixture

    from app.experiments.freight_continuous_analytics import (
        render_continuous_html,
        summarize_continuous,
    )

    verified = continuous_fixture()
    before = render_continuous_html(summarize_continuous(verified, tmp_path))
    assert "Measured vehicle capacity utilization" in before
    for snapshot in verified["snapshots"]:
        snapshot["vehicle_telemetry"] = fixture()["vehicle_telemetry"]
        for n, service in enumerate(snapshot["services"]):
            service["service"] = n
    after = render_continuous_html(summarize_continuous(verified, tmp_path))
    assert "Derived sampled vehicle capacity utilization" in after
    assert "Measured vehicle capacity utilization" not in after
