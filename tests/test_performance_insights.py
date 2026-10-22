"""Offline P07 performance insights; controlled fixtures establish no native run.

These tests only exercise the analytics layer over existing retained report
shapes (``summary.json`` / ``evaluation.json``), plus read-only real artifact
paths when they are present. Nothing here launches OpenTTD or mutates evidence.
"""

import copy
import json
from pathlib import Path

import pytest

from app.experiments.performance_insights import (
    MAX_SERIES_POINTS,
    analyze_performance,
    bottleneck_assessment,
    build_network_insights,
    build_performance_insights,
    compare_performance_rows,
    comparison_row,
    render_insights_charts,
    render_insights_markdown,
)

ATTEMPT19 = Path("artifacts/experiments/p07-attempt19-five-year-offline")
DEMO_REPORT = Path("artifacts/demos/playable-demo-25d891bc9f3444aca73058165d10055a-report")
ATTEMPT19_CLASSIFICATION = "OFFLINE_RECOVERED_REPLAY_VERIFIED_CONTINUOUS_OBSERVATIONS"
FAILED_TERMINAL = "Native terminal status: FAILED"


def continuous_fixture():
    """Small controlled continuous summary with the retained P07 field shape."""
    snapshots = []
    delivered_a = [0, 10, 10, 20, 20, 30, 30, 40, 40, 90]
    waiting_a = [0, 5, 0, 5, 0, 5, 2, 4, 10, 90]
    delivered_b = [0, 5, 5, 10, 10, 15, 15, 20, 20, 25]
    waiting_b = [0] * 10
    for index in range(10):
        snapshots.append(
            dict(
                sequence=index,
                economy_date=712299 + index * 30,
                elapsed_economy_days=index * 30,
                services=[
                    dict(
                        route_id="route-alpha",
                        delivered=delivered_a[index],
                        station_waiting_cargo=waiting_a[index],
                        cargo_load=0 if index < 4 else 40,
                        capacity=40,
                        vehicle=101,
                        revenue=None,
                    ),
                    dict(
                        route_id="route-beta",
                        delivered=delivered_b[index],
                        station_waiting_cargo=waiting_b[index],
                        cargo_load=40,
                        capacity=40,
                        vehicle=102,
                        revenue=None,
                    ),
                ],
            )
        )
    return dict(
        classification="CONTROLLED_TEST_CONTINUOUS",
        snapshots=snapshots,
        totals=[
            {
                "scope": "route-alpha",
                "revenue": None,
                "delivered_cargo": 90,
                "cargo_per_economy_day": 90 / 270,
            },
            {
                "scope": "route-beta",
                "revenue": None,
                "delivered_cargo": 25,
                "cargo_per_economy_day": 25 / 270,
            },
            {
                "scope": "network",
                "revenue": 500,
                "delivered_cargo": 115,
                "cargo_per_economy_day": 115 / 270,
            },
        ],
        finance=dict(
            freight_revenue=500,
            capex=300,
            opening_cash=1000,
            closing_cash=1100,
            known_unallocated_expenses=120,
            unknown_cash_movements=-10,
            vehicle_operating_expenses=None,
            operating_profit=None,
            roi=None,
        ),
        periods=[
            {
                "period": "annual",
                "index": 1,
                "scope": "network",
                "start_economy_date": 712299,
                "end_economy_date": 712299 + 366,
                "elapsed_economy_days": 366,
                "revenue": 250,
                "delivered_cargo": 30,
                "known_unallocated_expenses": 60,
            },
            {
                "period": "annual",
                "index": 2,
                "scope": "network",
                "start_economy_date": 712299 + 366,
                "end_economy_date": 714125,
                "elapsed_economy_days": 361,
                "revenue": 250,
                "delivered_cargo": 20,
                "known_unallocated_expenses": 60,
            },
        ],
        offline_recovery=dict(
            original_directory="controlled/attempt19",
            schema=1,
            original_terminal=dict(status="FAILED", preflight="PASS"),
        ),
        limitations=["Controlled fixture limitation retained verbatim."],
    )


def evaluation_fixture():
    """Small controlled network-evaluation document with the retained shape."""
    return dict(
        classification="CONTROLLED_BATCH",
        metrics=[
            {
                "name": "delivered_cargo",
                "unit": "cargo_units",
                "actual": "60",
                "planned": "60",
                "provenance": "Controlled batch total.",
            },
            {
                "name": "total_capex",
                "unit": "GBP",
                "actual": "28459",
                "planned": "28459",
                "provenance": "Controlled receipts.",
            },
            {
                "name": "delivery_revenue",
                "unit": "GBP",
                "actual": "200",
                "provenance": "Controlled batch revenue.",
            },
            {
                "name": "operating_costs",
                "unit": "GBP",
                "actual": None,
                "provenance": "Not collected.",
            },
            {
                "name": "net_return",
                "unit": "GBP",
                "actual": None,
                "provenance": "Not derivable.",
            },
        ],
        services=[
            {
                "route_id": "route-a",
                "status": "verified-delivery",
                "metrics": [
                    {"name": "delivered_cargo", "unit": "cargo_units", "actual": "20"},
                    {"name": "source_waiting", "unit": "cargo_units", "actual": "54"},
                ],
            },
            {
                "route_id": "route-b",
                "status": "verified-delivery",
                "metrics": [
                    {"name": "delivered_cargo", "unit": "cargo_units", "actual": "40"},
                    {"name": "source_waiting", "unit": "cargo_units", "actual": "42"},
                ],
            },
        ],
        feedback=[
            {
                "code": "source_waiting_backlog",
                "metric": "source_waiting",
                "actual": 54,
                "recommendation": "Measure repeat-trip queue growth before resizing fleets.",
            }
        ],
        game_time=dict(
            simulation_start_date=712223,
            final_cargo_delivery_date=712386,
            total_elapsed_economy_days=163,
        ),
        limitations=["Controlled batch limitation."],
    )


def metric(insights, name, scope=None):
    if scope is None:
        return next((m for m in insights.metrics if m.name == name), None)
    service = next((s for s in insights.services if s.scope == scope), None)
    return next((m for m in service.metrics if m.name == name), None)


def value_of(insights, name, scope=None):
    row = metric(insights, name, scope)
    return None if row is None else (None if row.status == "UNKNOWN" else row.value)


# ---------------------------------------------------------------------------
# Metric math and aggregation
# ---------------------------------------------------------------------------


def test_network_headline_metrics_are_network_level_not_service_first():
    insights = build_performance_insights(continuous_fixture())
    assert value_of(insights, "network_delivered_cargo") == 115
    assert value_of(insights, "network_revenue") == 500
    assert value_of(insights, "network_cargo_per_economy_day") == pytest.approx(115 / 270)
    # Service-level deltas use endpoint differences of cumulative counters.
    assert value_of(insights, "delivered_cargo", "route-alpha") == 90
    assert value_of(insights, "delivered_cargo", "route-beta") == 25
    assert value_of(insights, "cargo_per_economy_day", "route-alpha") == pytest.approx(90 / 270)
    ranks = {s.scope: s.rank_by_cargo_per_day for s in insights.services}
    assert ranks == {"route-alpha": 1, "route-beta": 2}
    assert value_of(insights, "observed_active_vehicles") == 2


def test_episode_coalescing_and_spacing_are_derived_from_deltas():
    insights = build_performance_insights(continuous_fixture())
    # route-alpha: flat samples separate delivery clusters; consecutive
    # positive increments inside a cluster stay coalesced.
    assert value_of(insights, "unloading_episodes", "route-alpha") == 5
    assert value_of(insights, "episode_spacing_min_days", "route-alpha") == 60
    assert value_of(insights, "episode_spacing_max_days", "route-alpha") == 60


def test_adjacent_positive_deltas_coalesce_into_one_episode():
    from app.experiments.performance_insights import _episodes, _spacing_days

    delivered = [0, 10, 20, 30, 30, 40]
    elapsed = [450000 + 30 * index for index in range(len(delivered))]
    episodes = _episodes(delivered, elapsed)
    assert [(e["index"], e["cargo"]) for e in episodes] == [(1, 30), (5, 10)]
    assert _spacing_days(episodes) == (120, 120)


def test_time_series_aggregates_network_and_downsamples_long_series():
    fixture = continuous_fixture()
    insights = build_performance_insights(fixture)
    network = insights.time_series["network"]
    assert [point.delivered for point in network] == [0, 15, 15, 30, 30, 45, 45, 60, 60, 115]
    assert [point.waiting for point in network] == [0, 5, 0, 5, 0, 5, 2, 4, 10, 90]
    long_fixture = continuous_fixture()
    long_fixture["snapshots"] = []
    for index in range(250):
        long_fixture["snapshots"].append(
            dict(
                sequence=index,
                economy_date=712299 + index,
                elapsed_economy_days=index,
                services=[
                    dict(
                        route_id="route-alpha",
                        delivered=index,
                        station_waiting_cargo=None,
                    )
                ],
            )
        )
    insights = build_performance_insights(long_fixture)
    points = insights.time_series["route-alpha"]
    assert len(points) <= MAX_SERIES_POINTS
    assert points[-1].delivered == 249


def test_interval_series_preserves_non_365_economy_year_windows():
    insights = build_performance_insights(continuous_fixture())
    annual = [row for row in insights.interval_series if row.period == "annual"]
    assert [row.elapsed_economy_days for row in annual] == [366, 361]
    assert annual[0].revenue == 250 and annual[0].known_unallocated_expenses == 60
    assert annual[1].end_economy_date == 714125


# ---------------------------------------------------------------------------
# Missing data, attribution and finance semantics
# ---------------------------------------------------------------------------


def test_unknown_measurements_stay_unknown_and_never_become_zero():
    fixture = continuous_fixture()
    del fixture["finance"]["freight_revenue"]
    del fixture["finance"]["closing_cash"]
    insights = build_performance_insights(fixture)
    for name in (
        "observed_gross_revenue",
        "vehicle_operating_expenses",
        "operating_profit",
        "roi",
    ):
        row = metric(insights, name)
        assert row is not None and row.status == "UNKNOWN" and row.value is None


def test_unknown_note_is_declared_in_limitations_and_missing_data_behavior():
    insights = build_performance_insights(continuous_fixture())
    assert any("UNKNOWN is not zero" in text for text in insights.limitations)
    assert any(
        "UNKNOWN" in row.missing_data_behavior
        for row in insights.metrics
        if row.status == "UNKNOWN"
    )


def test_service_revenue_stays_unknown_when_reservation_is_impossible():
    insights = build_performance_insights(continuous_fixture())
    for scope in ("route-alpha", "route-beta"):
        row = metric(insights, "service_revenue", scope)
        assert row.status == "UNKNOWN" and row.value is None
        assert "never" in row.missing_data_behavior
    assert value_of(insights, "network_revenue") == 500


def test_capex_opex_separation_and_unattributed_cash_are_preserved():
    insights = build_performance_insights(continuous_fixture())
    assert value_of(insights, "observed_capex") == 300
    assert metric(insights, "observed_capex").status == "OBSERVED"
    assert metric(insights, "vehicle_operating_expenses").status == "UNKNOWN"
    assert value_of(insights, "observed_aggregate_expenses") == 120
    assert value_of(insights, "unattributed_cash_movement") == -10
    assert value_of(insights, "net_cash_flow") == 100
    for name in ("operating_profit", "roi"):
        assert metric(insights, name).status == "UNKNOWN"


def test_incomplete_history_never_partially_sums_or_invents_rates():
    fixture = continuous_fixture()
    del fixture["totals"]
    del fixture["snapshots"][-1]["services"][1]["delivered"]
    del fixture["snapshots"][-1]["elapsed_economy_days"]
    insights = build_performance_insights(fixture)
    assert metric(insights, "network_delivered_cargo").status == "UNKNOWN"
    assert value_of(insights, "network_delivered_cargo") is None
    assert value_of(insights, "cargo_per_economy_day", "route-beta") is None
    assert metric(insights, "cargo_per_economy_day", "route-beta").status == "UNKNOWN"


# ---------------------------------------------------------------------------
# Bottleneck classification and advisory recommendations
# ---------------------------------------------------------------------------


def test_backlog_bottleneck_classifications_are_deterministic():
    insights = build_performance_insights(continuous_fixture())
    classified = {b.scope: b.classification for b in insights.bottlenecks}
    assert classified["route-alpha"] == "GROWING_BACKLOG_SAMPLE_HYPOTHESIS"
    assert classified["route-beta"] == "NO_SUSTAINED_BACKLOG_OBSERVED"
    by_scope = {b.scope: b for b in insights.bottlenecks}
    assert by_scope["route-alpha"].status == "HYPOTHESIS"
    assert by_scope["route-alpha"].data_status == "SUFFICIENT"
    assert by_scope["route-beta"].status == "DERIVED"
    capacity_series = dict(
        scope="route-gamma",
        label="Service 3",
        dates=list(range(10)),
        elapsed=list(range(0, 300, 30)),
        delivered=[0, 10, 10, 20, 20, 30, 30, 40, 40, 50],
        waiting=[1, 1, 1, 0, 1, 1, 0, 1, 0, 1],
        cargo_load=[40] * 10,
        capacity=[40] * 10,
        vehicle=[7],
        stops=[None] * 10,
    )
    assessment = bottleneck_assessment(capacity_series, "controlled")
    assert assessment.classification == "CAPACITY_BOTTLENECK_HYPOTHESIS"
    assert assessment.status == "HYPOTHESIS"
    assert "hypothesis" in by_scope["route-alpha"].reasoning.lower()


def test_series_with_no_waiting_observations_is_insufficient_never_zero():
    series = dict(
        scope="route-gamma",
        label="Service 1",
        dates=[1],
        elapsed=[0],
        delivered=[0],
        waiting=[None],
        cargo_load=[None],
        capacity=[None],
        vehicle=[None],
        stops=[],
    )
    assessment = bottleneck_assessment(series, "controlled")
    assert assessment.classification == "INSUFFICIENT_DATA"
    assert assessment.status == "UNKNOWN" and assessment.data_status == "INSUFFICIENT_DATA"
    assert assessment.observations == {}


def test_batch_evidence_reports_no_series_but_keeps_endpoint_waiting():
    insights = build_network_insights(evaluation_fixture())
    assert all(
        b.classification == "NO_SERIES_IN_RETAINED_BATCH_EVIDENCE" for b in insights.bottlenecks
    )
    assert all(b.data_status == "INSUFFICIENT_DATA" for b in insights.bottlenecks)
    waiting = {
        b.scope: b.observations.get("endpoint_source_waiting_units") for b in insights.bottlenecks
    }
    assert waiting["route-a"] == 54 and waiting["route-b"] == 42
    assert next(m for m in insights.metrics if m.name == "operating_costs").status == "UNKNOWN"


def test_recommendations_are_deterministic_and_always_advisory():
    first = build_performance_insights(continuous_fixture()).recommendations
    second = build_performance_insights(continuous_fixture()).recommendations
    assert [row.recommendation_id for row in first] == [row.recommendation_id for row in second]
    for index, row in enumerate(first, 1):
        assert row.recommendation_id == f"rec-{index:03d}-{row.code}"
    codes = {row.code for row in first}
    assert "capacity_bottleneck_candidate" in codes or "backlog_growth_watch" in codes
    for row in first:
        assert row.advisory_only is True
        assert row.confidence in {"OBSERVED", "DERIVED", "HYPOTHESIS", "UNKNOWN"}
        assert row.suggested_next_experiment
        assert row.missing_information


def test_recommendations_claim_no_causality_and_no_income_from_residue():
    insights = build_performance_insights(continuous_fixture())
    words = ("hypothesis", "may", "unproven", "candidate", "suggest", "measurable")
    for row in insights.recommendations:
        if row.confidence == "HYPOTHESIS":
            text = f"{row.reason} {row.expected_improvement_direction}".lower()
            assert any(word in text for word in words), row.recommendation_id
        assert "proven" not in row.reason.lower() or "not" in row.reason.lower()
        # Advisory rows never promise a measured gain.
        assert "will increase" not in row.reason.lower()
        assert "improves" not in f"{row.reason} {row.expected_improvement_direction}".lower()
    roi_rows = [m for m in insights.metrics if m.name == "roi"]
    assert roi_rows and all(m.status == "UNKNOWN" for m in roi_rows)
    assert not [m for m in insights.metrics if m.status == "HYPOTHESIS"]


# ---------------------------------------------------------------------------
# Comparisons
# ---------------------------------------------------------------------------


def _row(run_id, cargo, days, world):
    return dict(
        run_id=run_id,
        source=f"{run_id}/summary.json",
        source_kind="continuous",
        classification="C",
        world_identity=world,
        configuration=None,
        observation_days=days,
        cargo_delivered=cargo,
        revenue_gbp=100,
        capex_gbp=50,
        cargo_per_day=cargo / days if cargo and days else None,
        revenue_per_day=100 / days if days else None,
        revenue_per_cargo=100 / cargo if cargo else None,
    )


def test_comparison_labels_matched_unrelated_and_insufficient_rows():
    same_world = {"seed": "42", "width": "64"}
    other_world = {"seed": "7", "width": "128"}
    matched = compare_performance_rows(
        [_row("a", 100, 10, same_world), _row("b", 60, 5, same_world)]
    )
    assert matched["classification"] == "MATCHED_WORLD_COMPARISON"
    assert matched["matched_pairs"] == [["a", "b"]]
    assert {row["run_id"]: row["status"] for row in matched["rows"]} == {
        "a": "MATCHED_DESCRIPTIVE",
        "b": "MATCHED_DESCRIPTIVE",
    }
    unrelated = compare_performance_rows(
        [_row("a", 100, 10, same_world), _row("b", 60, 5, other_world)]
    )
    assert unrelated["classification"] == "DESCRIPTIVE_UNRELATED_COMPARISON"
    assert unrelated["matched_pairs"] == []
    assert unrelated["rows"][1]["status"] == "UNRELATED_WORLD"
    insufficient = compare_performance_rows(
        [_row("a", None, 10, same_world), _row("b", 60, 5, same_world)]
    )
    statuses = {row["run_id"]: row["status"] for row in insufficient["rows"]}
    assert statuses == {"a": "INSUFFICIENT_DATA", "b": "INSUFFICIENT_DATA"}
    assert insufficient["classification"] == "INSUFFICIENT_DATA"
    assert insufficient["matched_pairs"] == []
    assert insufficient["matched_worlds"] == [["a", "b"]]
    # Unknown world identity is never presented as UNRELATED_WORLD.
    unknown_identity = compare_performance_rows([_row("a", 100, 10, None), _row("b", 60, 5, None)])
    statuses = {row["run_id"]: row["status"] for row in unknown_identity["rows"]}
    assert statuses == {"a": "INSUFFICIENT_DATA", "b": "INSUFFICIENT_DATA"}
    assert unknown_identity["classification"] == "INSUFFICIENT_DATA"
    # Lines with a zero-day window cannot be normalized.
    all_zero = compare_performance_rows(
        [_row("a", 100, 0, same_world), _row("b", 60, 0, same_world)]
    )
    assert all_zero["classification"] == "INSUFFICIENT_DATA"
    assert "never causal" in matched["policy"]


def test_world_identity_is_read_from_retained_prelaunch_records(tmp_path):
    from app.experiments.performance_insights import _world_identity

    source = tmp_path / "source"
    source.mkdir()
    document = continuous_fixture()
    (source / "summary.json").write_text(json.dumps(document))
    (source / "PRELAUNCH.json").write_text(
        json.dumps({"world": {"seed": 42, "width": 64, "height": 64}})
    )
    identity = _world_identity(source, document)
    assert identity == {"height": "64", "seed": "42", "width": "64"}
    insights = build_performance_insights(document, world_identity=identity)
    row = comparison_row(insights, run_id="source")
    assert row["cargo_delivered"] == 115
    assert row["world_identity"] == {"height": "64", "seed": "42", "width": "64"}
    # A document without retained PRELAUNCH references yields no identity, and
    # comparisons then refuse to call the runs unrelated to each other.
    bare = tmp_path / "bare"
    bare.mkdir()
    (bare / "summary.json").write_text(json.dumps(document))
    assert _world_identity(bare, document) is None
    other = tmp_path / "other"
    other.mkdir()
    (other / "summary.json").write_text(json.dumps(document))
    comparison = analyze_performance(bare, tmp_path / "out", compare=(other.resolve(),))
    assert comparison["classification"] == "CONTROLLED_TEST_CONTINUOUS"
    parsed = json.loads((tmp_path / "out" / "insights.json").read_text())
    assert parsed["comparisons"]["classification"] == "INSUFFICIENT_DATA"
    statuses = {row["run_id"]: row["status"] for row in parsed["comparisons"]["rows"]}
    assert statuses == {"bare": "INSUFFICIENT_DATA", "other": "INSUFFICIENT_DATA"}
    # The per-run cargo must still be normalized from the retained totals.
    cargo = {row["run_id"]: row["cargo_delivered"] for row in parsed["comparisons"]["rows"]}
    assert cargo == {"bare": 115, "other": 115}


# ---------------------------------------------------------------------------
# Builders over both retained document shapes
# ---------------------------------------------------------------------------


def test_network_evaluation_builder_keeps_unknown_not_zero_and_feedback():
    insights = build_network_insights(evaluation_fixture())
    assert insights.classification == "CONTROLLED_BATCH"
    assert insights.observation_window == {
        "start_economy_date": 712223,
        "end_economy_date": 712386,
        "economy_days": 163,
        "samples": None,
    }
    assert value_of(insights, "operation_window_days") == 163
    assert value_of(insights, "total_capex") == 28459
    for name in ("operating_costs", "net_return"):
        row = metric(insights, name)
        assert row.status == "UNKNOWN" and row.value is None
    codes = {row.code for row in insights.recommendations}
    assert "source_waiting_backlog" in codes
    assert "expense_attribution_gap" in codes
    assert "revenue_to_capex_review" in codes


def test_builder_dispatch_and_lifecycle_fields_from_continuous_fixture():
    insights = build_performance_insights(continuous_fixture())
    assert insights.source_kind == "continuous"
    assert insights.classification == "CONTROLLED_TEST_CONTINUOUS"
    assert insights.native_terminal_status == (
        "FAILED (historical native terminal; metadata derived offline)"
    )
    assert insights.observation_window["economy_days"] == 270
    assert insights.observation_window["samples"] == 10
    assert "Controlled fixture limitation retained verbatim." in insights.limitations
    with pytest.raises(ValueError, match="neither a continuous summary nor a network evaluation"):
        build_performance_insights({"unrelated": True})


# ---------------------------------------------------------------------------
# Real retained artifacts (read-only; skipped when absent)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not ATTEMPT19.is_dir(), reason="retained attempt 19 summary unavailable")
def test_real_attempt19_summary_keeps_failed_terminal_and_headline_math():
    document = json.loads((ATTEMPT19 / "summary.json").read_text())
    insights = build_performance_insights(
        document,
        source_kind="continuous",
        source_ref=str(ATTEMPT19 / "summary.json"),
    )
    assert insights.classification == ATTEMPT19_CLASSIFICATION
    assert insights.native_terminal_status.startswith("FAILED")
    assert value_of(insights, "network_delivered_cargo") == 2980
    assert value_of(insights, "network_revenue") == 50935
    assert value_of(insights, "observed_capex") == 28459
    assert value_of(insights, "observed_aggregate_expenses") == 16312
    for name in ("operating_profit", "roi", "vehicle_operating_expenses"):
        assert metric(insights, name).status == "UNKNOWN"
    assert all(
        assessment.classification == "CAPACITY_BOTTLENECK_HYPOTHESIS"
        for assessment in insights.bottlenecks
    )


@pytest.mark.skipif(not DEMO_REPORT.is_dir(), reason="fixed demo report unavailable")
def test_real_fixed_demo_evaluation_is_read_only_and_unknown_aware():
    document = json.loads((DEMO_REPORT / "evaluation.json").read_text())
    insights = build_network_insights(document, source_ref=str(DEMO_REPORT / "evaluation.json"))
    assert insights.classification == "NATIVE_MULTI_SERVICE_EVALUATION"
    assert value_of(insights, "delivered_cargo") == 60
    assert value_of(insights, "total_capex") == 28459
    assert value_of(insights, "operation_window_days") == 163
    for name in ("operating_costs", "net_return"):
        assert metric(insights, name).status == "UNKNOWN"
    assert insights.services and insights.services[0].status == "verified-delivery"
    waiting = {
        b.scope: b.observations.get("endpoint_source_waiting_units") for b in insights.bottlenecks
    }
    assert waiting[insights.services[0].scope] == 54


# ---------------------------------------------------------------------------
# Pipeline and reporting
# ---------------------------------------------------------------------------


def test_analyze_performance_writes_outputs_and_preserves_failed_terminal(tmp_path):
    source = tmp_path / "attempt"
    source.mkdir()
    (source / "summary.json").write_text(json.dumps(continuous_fixture()))
    result = analyze_performance(source, tmp_path / "out")
    assert result["classification"] == "CONTROLLED_TEST_CONTINUOUS"
    for name in (
        "insights.json",
        "performance-report.md",
        "terminal-summary.txt",
        "insights-charts.html",
    ):
        assert (tmp_path / "out" / name).is_file()
    parsed = json.loads((tmp_path / "out" / "insights.json").read_text())
    assert parsed["schema_version"] == 1
    assert parsed["native_terminal_status"].startswith("FAILED")
    report = (tmp_path / "out" / "performance-report.md").read_text()
    summary = (tmp_path / "out" / "terminal-summary.txt").read_text()
    charts = (tmp_path / "out" / "insights-charts.html").read_text()
    assert FAILED_TERMINAL in report and FAILED_TERMINAL in summary
    assert "UNKNOWN is not zero" in summary
    assert "UNKNOWN is never zero" in charts
    assert "<svg" in charts and "<script" not in charts
    assert "no profit" in summary
    assert parsed["comparisons"] is None


def test_analyze_performance_writes_comparison_with_world_identity(tmp_path):
    primary, other = tmp_path / "primary", tmp_path / "other"
    for root in (primary, other):
        root.mkdir()
        (root / "summary.json").write_text(json.dumps(continuous_fixture()))
        (root / "PRELAUNCH.json").write_text(
            json.dumps({"world": {"seed": 42, "width": 64, "height": 64}})
        )
    result = analyze_performance(
        primary,
        tmp_path / "out",
        compare=(other.resolve(),),
    )
    assert result["comparison"] is not None
    document = json.loads((tmp_path / "out" / "insights.json").read_text())
    comparison = document["comparisons"]
    assert comparison["classification"] == "MATCHED_WORLD_COMPARISON"
    assert comparison["matched_pairs"] == [["primary", "other"]]
    statuses = {row["run_id"]: row["status"] for row in comparison["rows"]}
    assert statuses == {"primary": "MATCHED_DESCRIPTIVE", "other": "MATCHED_DESCRIPTIVE"}
    # Primary insights keep their expert fields; comparisons only annotate.
    assert document["source_kind"] == "continuous"


def test_output_inside_retained_source_is_rejected(tmp_path):
    source = tmp_path / "attempt"
    other = tmp_path / "other"
    for root in (source, other):
        root.mkdir()
        (root / "summary.json").write_text(json.dumps(continuous_fixture()))
    with pytest.raises(ValueError, match="must not modify retained evidence"):
        analyze_performance(source, source / "insights")
    with pytest.raises(ValueError, match="must not modify retained evidence"):
        analyze_performance(source, other / "insights", compare=(other.resolve(),))
    assert not (source / "insights").exists()
    assert not (other / "insights").exists()
    assert sorted(p.name for p in source.iterdir()) == ["summary.json"]


def test_cli_rejects_missing_source_without_output(tmp_path):
    from app.experiments.cli import main

    output = tmp_path / "out"
    assert (
        main(
            [
                "analyze-performance-insights",
                str(tmp_path / "missing"),
                "--output",
                str(output),
            ]
        )
        == 1
    )
    assert not output.exists()


def test_contract_renderers_never_invent_zero_and_state_is_json_round_trippable():
    insights = build_performance_insights(continuous_fixture())
    dump = json.loads(insights.model_dump_json())
    rebuilt = type(insights).model_validate(dump)
    assert rebuilt.metrics == insights.metrics
    assert all(part["advisory_only"] for part in dump["recommendations"])
    for metric_row in dump["metrics"]:
        assert set(metric_row) >= {
            "name",
            "unit",
            "status",
            "observation_period",
            "source",
            "derivation",
            "missing_data_behavior",
        }
    markdown = render_insights_markdown(insights)
    for phrase in (
        FAILED_TERMINAL,
        "## Headline metrics",
        "## Bottleneck analysis",
        "## Recommendations (advisory only)",
        "UNKNOWN is not zero",
    ):
        assert phrase in markdown
    charts = render_insights_charts(insights)
    assert "<svg" in charts and "UNKNOWN is never zero" in charts


def test_contract_models_are_frozen_and_forbid_extra():
    from pydantic import ValidationError

    fixture = continuous_fixture()
    insights = build_performance_insights(fixture)
    metric = insights.metrics[0]
    with pytest.raises(ValidationError):  # frozen Contract refuses mutation
        metric.value = 8
    extra = copy.deepcopy(insights.model_dump())
    extra["not_a_field"] = 1
    with pytest.raises(ValidationError):  # extra="forbid"
        type(insights).model_validate(extra)
    with pytest.raises(ValidationError):
        type(insights).model_validate(insights.model_dump() | {"schema_version": 2})


def test_full_stack_network_and_limitation_pass_through_is_explicit():
    fixture = evaluation_fixture()
    insights = build_network_insights(fixture)
    limitations = insights.limitations
    assert "Controlled batch limitation." in limitations
    assert any("UNKNOWN is not zero" in line for line in limitations)
    assert all(
        recommendation.scope in {"route-a", "route-b", "network"}
        for recommendation in insights.recommendations
    )
    copy_model = insights.model_copy(deep=True)
    assert copy_model == insights
