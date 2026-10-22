"""Controlled P07 reporting; these fixtures do not establish native execution."""

import copy
import json

import pytest

from app.experiments.freight_continuous_analytics import (
    analyze_continuous,
    render_continuous_html,
    summarize_continuous,
)


def fixture():
    snapshots = []
    for month in range(61):
        snapshots.append(
            dict(
                sequence=month,
                economy_date=700000 + month * 30,
                economy_year=1950 + month // 12,
                economy_month=month % 12 + 1,
                economy_day=1,
                elapsed_economy_days=month * 30,
                script_tick=month * 2000,
                wall_elapsed_seconds=month * 60,
                services=[
                    dict(
                        route_id=f"route-{i}",
                        revenue=month * i * 100,
                        delivered=month * i * 20,
                        completed_delivery_cycles=month * i,
                        operating_costs=None,
                        capacity_utilization=None,
                        station_waiting_cargo=month * i,
                    )
                    for i in (1, 2, 3)
                ],
                finance=dict(
                    cash=500000 + month * 600,
                    loan_balance=10000,
                    quarter_income=(month % 3) * 600,
                    quarter_expenses=0,
                    quarter_delivered=(month % 3) * 120,
                    previous_quarter_income=1800,
                    previous_quarter_expenses=0,
                    previous_quarter_delivered=360,
                    clock=dict(
                        economy_date=700000 + month * 30,
                        economy_year=1950 + month // 12,
                        economy_month=month % 12 + 1,
                    ),
                ),
                source_digests=[f"controlled-exchange-{month}"],
            )
        )
    return dict(
        snapshots=snapshots,
        monthly=snapshots[1:],
        quarterly=snapshots[3::3],
        annual=snapshots[12::12],
        summary=dict(
            status="CONTROLLED",
            completed_years=5,
            infrastructure_and_vehicle_capex_gbp=28459,
            financial_metrics=dict(operating_profit=None, roi=None),
        ),
        complete=True,
    )


def test_five_year_service_and_network_aggregation_with_provenance(tmp_path):
    report = summarize_continuous(fixture(), tmp_path)
    months = [row for row in report["periods"] if row["period"] == "monthly"]
    years = [row for row in report["periods"] if row["period"] == "annual"]
    quarters = [row for row in report["periods"] if row["period"] == "quarterly"]
    assert len(months) == 60 * 4 and len(years) == 5 * 4 and len(quarters) == 20 * 4
    assert next(row for row in months if row["scope"] == "network")["revenue"] == 600
    assert next(row for row in years if row["scope"] == "network")["delivered_cargo"] == 1440
    assert report["totals"][-1]["revenue"] == 36000
    assert report["totals"][-1]["delivered_cargo"] == 7200
    for row in report["periods"]:
        assert all(reference in report["evidence"] for reference in row["evidence_refs"])
        assert row["vehicle_operating_expenses"] is None
    assert report["evidence"]["0"]["source_digests"] == ["controlled-exchange-0"]
    assert len(report["evidence"]["0"]["sha256"]) == 64


def test_unknown_service_values_do_not_hide_measured_network_or_become_zero(tmp_path):
    controlled = fixture()
    for snapshot in controlled["snapshots"]:
        for service in snapshot["services"]:
            service["revenue"] = None
        snapshot["finance"]["quarter_income"] = (snapshot["sequence"] % 3) * 777
        snapshot["finance"]["previous_quarter_income"] = 3 * 777
    report = summarize_continuous(controlled, tmp_path)
    assert all(row["revenue"] is None for row in report["totals"][:-1])
    assert report["totals"][-1]["revenue"] == 60 * 777
    assert all(row["vehicle_operating_expenses"] is None for row in report["periods"])
    html = render_continuous_html(report)
    for title in (
        "Monthly revenue",
        "Annual delivered cargo",
        "Service-level revenue comparison",
        "Cash balance over time",
        "Measured operating costs",
        "Station cargo backlog",
        "Measured vehicle capacity utilization",
        "Cumulative revenue vs CAPEX",
        "Break-even analysis",
    ):
        assert title in html
    assert 'class="unknown">unknown' in html
    assert "<script" not in html
    assert "UNKNOWN is never zero" in html


def test_annual_elapsed_dates_do_not_assume_365_days(tmp_path):
    controlled = fixture()
    controlled["snapshots"][12]["economy_date"] = 700366
    controlled["snapshots"][24]["economy_date"] = 700731
    controlled["annual"] = copy.deepcopy(controlled["annual"][:2])
    controlled["annual"][0]["economy_date"] = 700366
    controlled["annual"][1]["economy_date"] = 700731
    report = summarize_continuous(controlled, tmp_path)
    annual = [
        row for row in report["periods"] if row["period"] == "annual" and row["scope"] == "network"
    ]
    assert [row["elapsed_economy_days"] for row in annual] == [366, 365]
    assert annual[0]["revenue_per_economy_day"] == 7200 / 366


def test_partial_observation_is_reported_without_invented_complete_years(tmp_path):
    controlled = fixture()
    controlled["snapshots"] = controlled["snapshots"][:5]
    controlled["monthly"] = controlled["snapshots"][1:]
    controlled["quarterly"] = controlled["snapshots"][3::3]
    controlled["annual"] = []
    controlled["summary"] = dict(status="INTERRUPTED", completed_years=0)
    controlled["complete"] = False
    report = summarize_continuous(controlled, tmp_path)
    assert report["lifecycle"]["status"] == "INTERRUPTED"
    assert not any(row["period"] == "annual" for row in report["periods"])
    assert report["totals"][-1]["revenue"] == 2400


def test_analysis_replays_before_writing_and_rejects_evidence_output(tmp_path, monkeypatch):
    import app.simulation.openttd.freight_continuous as monitor

    source, output = tmp_path / "source", tmp_path / "output"
    source.mkdir()
    calls = []

    def verify(path):
        calls.append(path)
        return fixture()

    monkeypatch.setattr(monitor, "verify_continuous_evidence", verify)
    with pytest.raises(ValueError, match="must not modify"):
        analyze_continuous(source, source / "analytics")
    assert calls == []
    assert analyze_continuous(source, output)["periods"] == (60 + 20 + 5) * 4
    assert calls == [source.resolve()]
    assert json.loads((output / "summary.json").read_text())["totals"][-1]["revenue"] == 36000
    assert (output / "metrics.csv").read_text().count("monthly,") == 240
    (output / "charts.html").unlink()
    (output / "charts.html").symlink_to(source / "retained.html")
    with pytest.raises(ValueError, match="must not modify"):
        analyze_continuous(source, output)
    assert not (source / "retained.html").exists()


def test_cli_rejects_missing_evidence_without_output(tmp_path):
    from app.experiments.cli import main

    output = tmp_path / "output"
    assert (
        main(["analyze-continuous-freight", str(tmp_path / "missing"), "--output", str(output)])
        == 1
    )
    assert not output.exists()


def test_network_utilization_is_capacity_weighted_not_sum_of_ratios(tmp_path):
    controlled = fixture()
    for snapshot in controlled["snapshots"]:
        for service, capacity, load in zip(
            snapshot["services"], (10, 20, 70), (5, 20, 0), strict=True
        ):
            service["capacity"] = capacity
            service["cargo_load"] = load
            service["capacity_utilization"] = load / capacity
    from app.experiments.freight_continuous_analytics import _metric

    report = summarize_continuous(controlled, tmp_path)
    assert _metric(report["snapshots"][-1], "network", "capacity_utilization") == 0.25


def test_partial_keeps_verified_construction_capex_without_complete_summary(tmp_path):
    controlled = fixture()
    controlled["complete"] = False
    controlled["summary"] = None
    controlled["infrastructure_and_vehicle_capex_gbp"] = 28459
    for n in range(3):
        (tmp_path / f"service-receipt-{n}.json").write_text('{"controlled":true}')
    report = summarize_continuous(controlled, tmp_path)
    assert report["finance"]["capex"] == 28459
    assert len(report["capex_provenance"]) == 3
    assert all(len(ref["sha256"]) == 64 for ref in report["capex_provenance"])
    assert "28459" in render_continuous_html(report)
    assert report["classification"] == "REPLAY_VERIFIED_PARTIAL_CONTINUOUS_OBSERVATIONS"


def test_observed_aggregate_expenses_chart_preserves_unknown_vehicle_opex(tmp_path):
    controlled = fixture()
    for snapshot in controlled["snapshots"]:
        month = snapshot["sequence"]
        snapshot["finance"]["quarter_expenses"] = -(month % 3) * 37
        snapshot["finance"]["previous_quarter_expenses"] = -3 * 37
    report = summarize_continuous(controlled, tmp_path)
    monthly = [row for row in report["periods"] if row["period"] == "monthly"]
    assert all(
        row["known_unallocated_expenses"] == 37 for row in monthly if row["scope"] == "network"
    )
    assert all(
        row["known_unallocated_expenses"] is None for row in monthly if row["scope"] != "network"
    )
    assert all(row["vehicle_operating_expenses"] is None for row in monthly)
    html = render_continuous_html(report)
    assert "Observed company aggregate expenses (unallocated categories)" in html
    assert ">37</text>" in html
    assert all(row["evidence_refs"] for row in monthly)


def test_setup_cash_gap_uses_operation_boundary_without_double_counting(tmp_path):
    controlled = fixture()
    controlled["snapshots"][0]["finance"].update(
        cash=471156,
        quarter_expenses=-335,
        previous_quarter_income=0,
        previous_quarter_expenses=0,
    )
    (tmp_path / "scenario-capital.json").write_text(
        json.dumps(
            dict(
                independently_verified=True,
                balance_after=500000,
                expenses_after=0,
                income_after=0,
                loan_after=10000,
            )
        )
    )
    report = summarize_continuous(controlled, tmp_path)
    coverage = report["setup_cash_coverage"]
    assert coverage["setup_cash_decrease_excluding_capex"] == 385
    assert coverage["opening_quarter_expenses_signed"] == -335
    assert coverage["setup_expense_categories"] is None
    assert coverage["measured_setup_aggregate_expenses"] == 335
    assert coverage["unattributed_setup_cash_decrease"] == 50
    assert report["finance"]["operating_profit"] is None
    assert report["finance"]["roi"] is None
    assert len(coverage["evidence"][0]["sha256"]) == 64


def test_recovered_analysis_preserves_failed_native_status(tmp_path, monkeypatch):
    import app.simulation.openttd.freight_continuous as monitor

    controlled = fixture()
    controlled["offline_recovery"] = dict(
        historical_status="FAILED", classification="DERIVED_OFFLINE"
    )
    calls = []

    def verify(source, *, recovery_directory):
        calls.append((source, recovery_directory))
        return controlled

    monkeypatch.setattr(monitor, "verify_continuous_evidence", verify)
    source, recovery, output = tmp_path / "source", tmp_path / "recovery", tmp_path / "output"
    source.mkdir()
    analyze_continuous(source, output, recovery_directory=recovery)
    assert calls == [(source.resolve(), recovery)]
    report = json.loads((output / "summary.json").read_text())
    assert report["offline_recovery"]["historical_status"] == "FAILED"
    assert "Historical native attempt remains FAILED" in (output / "charts.html").read_text()


def test_chart_labels_are_short_and_legend_preserves_route_vehicle_mapping(tmp_path):
    controlled = fixture()
    original = "p05-route-" + "a" * 64
    for snapshot in controlled["snapshots"]:
        snapshot["services"][0].update(route_id=original, vehicle=4)
    report = summarize_continuous(controlled, tmp_path)
    html = render_continuous_html(report)
    assert f"Service 1: <code>{original}</code>; vehicle 4" in html
    assert ">1 Service 1</text>" in html
    assert ">Network</text>" in html
    assert f">{original}</text>" not in html
    assert report["totals"][0]["scope"] == original
    assert report["periods"][0]["scope"] == original
