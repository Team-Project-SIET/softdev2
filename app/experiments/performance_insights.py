"""P07 performance insights over existing offline analytics artifacts.

This layer answers: how well did the freight network perform, which services
performed better or worse, where are likely bottlenecks, and what should the
optimizer consider next. It consumes an existing P07 document (a continuous
``summary.json`` or a network ``evaluation.json``), never verifies native
evidence again, never launches anything and never issues commands: every
recommendation is advisory and every metric declares its unit, observation
window, source, derivation, missing-data behaviour and
OBSERVED/DERIVED/HYPOTHESIS/UNKNOWN status.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from app.experiments.freight_analytics import _bars
from app.planning.domain import Contract

SCHEMA_VERSION = 1
MAX_SERIES_POINTS = 200
EVIDENCE = Literal["OBSERVED", "DERIVED", "HYPOTHESIS", "UNKNOWN"]
COMPARISON_STATUS = Literal["MATCHED_DESCRIPTIVE", "UNRELATED_WORLD", "INSUFFICIENT_DATA"]

OUTPUT_NAMES = (
    "insights.json",
    "performance-report.md",
    "terminal-summary.txt",
    "insights-charts.html",
    "comparison.json",
)

UNKNOWN_NOTE = "UNKNOWN is not zero."

ADVISORY_NOTE = (
    "Advisory analysis over retained offline evidence; no P05 objective, vehicle "
    "purchase, construction or native execution is modified by this layer."
)

_BASE_LIMITATIONS = (
    ADVISORY_NOTE,
    "Insights derive from the already-verified P07 document; verification is not repeated.",
    UNKNOWN_NOTE,
    "Backlog is a point sample of station waiting cargo, not unmet demand.",
    "Episode rates use retained samples and include setup and waiting; they are not "
    "steady-state throughput.",
    "Full OPEX, net profit and ROI remain UNKNOWN without complete expense attribution.",
)

_BOTTLENECK_MISSING = (
    "Station capacity and industry production counters are not retained; cumulative "
    "production and lost cargo cannot be inferred from a fluctuating queue.",
    "No departure/arrival duration series establishes travel time; no occupancy counter "
    "establishes road, depot or station saturation.",
    "Failed or abandoned deliveries are not counters in retained evidence.",
)

_CAPACITY_EXPERIMENT_TEXT = (
    "Matched baseline versus increased effective fleet capacity on the affected "
    "service, holding the source world, observation horizon and route geometry fixed; "
    "reuse app/experiments/capacity_experiment.py A/B contracts, and any native A/B "
    "requires a fresh reviewed authorization."
)

_FREQUENCY_EXPERIMENT_TEXT = (
    "Matched baseline versus higher dispatch frequency on the same frozen world and "
    "horizon; a native comparison needs a reviewed one-shot authorization."
)

_ROUTING_EXPERIMENT_TEXT = (
    "Compare the retained route geometry against alternative bounded P08 corridor "
    "candidates offline before any native change; no automatic replanning."
)


def _number(value) -> int | float | None:
    """Native and evaluated JSON values may arrive as Decimal strings."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    return int(amount) if amount == amount.to_integral_value() else float(amount)


def _fmt(value) -> str:
    if value is None:
        return "UNKNOWN"
    if isinstance(value, (int, float)):
        return f"{value:g}"
    return str(value)


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


class DeclaredMetric(Contract):
    name: str
    unit: str
    status: EVIDENCE
    value: int | float | None = None
    observation_period: str
    source: str
    derivation: str
    missing_data_behavior: str
    limitations: str = ""


class ServicePerformance(Contract):
    scope: str
    label: str
    status: str | None = None
    vehicle: int | None = None
    metrics: list[DeclaredMetric]
    rank_by_cargo_per_day: int | None = None


class BottleneckAssessment(Contract):
    scope: str
    label: str
    classification: Literal[
        "CAPACITY_BOTTLENECK_HYPOTHESIS",
        "GROWING_BACKLOG_SAMPLE_HYPOTHESIS",
        "NO_SUSTAINED_BACKLOG_OBSERVED",
        "NO_SERIES_IN_RETAINED_BATCH_EVIDENCE",
        "INSUFFICIENT_DATA",
    ]
    status: Literal["HYPOTHESIS", "DERIVED", "UNKNOWN"]
    data_status: Literal["SUFFICIENT", "INSUFFICIENT_DATA"]
    observations: dict[str, Any]
    evidence: list[str]
    reasoning: str
    missing_information: list[str]


class AdvisoryRecommendation(Contract):
    recommendation_id: str
    code: str
    scope: str
    confidence: EVIDENCE
    reason: str
    evidence: list[str]
    expected_improvement_direction: str
    advisory_only: bool = True
    missing_information: list[str]
    suggested_next_experiment: str


class SeriesPoint(Contract):
    economy_date: int
    delivered: int | float | None
    waiting: int | None
    cargo_load: int | None
    capacity: int | None


class IntervalPoint(Contract):
    period: str
    index: int
    scope: str
    start_economy_date: int
    end_economy_date: int
    elapsed_economy_days: int | None
    revenue: int | float | None
    delivered_cargo: int | float | None
    known_unallocated_expenses: int | float | None


class ComparisonRow(Contract):
    run_id: str
    source: str
    source_kind: str
    classification: str
    world_identity: dict[str, str] | None
    configuration: str | None
    observation_days: int | None
    cargo_delivered: int | None
    revenue_gbp: int | None
    capex_gbp: int | None
    cargo_per_day: float | None
    revenue_per_day: float | None
    revenue_per_cargo: float | None
    status: COMPARISON_STATUS


class PerformanceInsights(Contract):
    schema_version: Literal[1]
    classification: str
    source_kind: Literal["continuous", "network-evaluation"]
    source_ref: str
    source_sha256: str | None = None
    native_terminal_status: str | None = None
    world_identity: dict[str, str] | None = None
    observation_window: dict[str, int | None]
    metrics: list[DeclaredMetric]
    services: list[ServicePerformance]
    time_series: dict[str, list[SeriesPoint]]
    interval_series: list[IntervalPoint]
    bottlenecks: list[BottleneckAssessment]
    recommendations: list[AdvisoryRecommendation]
    limitations: list[str]
    comparisons: dict[str, Any] | None = None
    financial_attribution: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Series extraction and bottleneck detection
# ---------------------------------------------------------------------------


def _service_index(snapshot: dict, index: int) -> dict:
    services = snapshot.get("services") or []
    return services[index] if index < len(services) else {}


def _complete_sum(values):
    return sum(values) if values and all(v is not None for v in values) else None


def _service_series(report: dict) -> list[dict]:
    """Extract retained per-service series with native field fallbacks."""
    snapshots = report.get("snapshots") or []
    if not snapshots:
        return []
    heads = snapshots[0].get("services") or []
    series = []
    for index, head in enumerate(heads):
        rows: dict[str, list] = {
            key: []
            for key in ("delivered", "waiting", "cargo_load", "capacity", "vehicle", "stops")
        }
        dates, elapsed = [], []
        for snapshot in snapshots:
            service = _service_index(snapshot, index)
            dates.append(snapshot.get("economy_date"))
            elapsed.append(snapshot.get("elapsed_economy_days"))
            rows["delivered"].append(
                _number(service.get("delivered", service.get("delivered_cargo")))
            )
            rows["waiting"].append(
                _number(service.get("station_waiting", service.get("station_waiting_cargo")))
            )
            rows["cargo_load"].append(_number(service.get("cargo_load")))
            rows["capacity"].append(_number(service.get("capacity")))
            rows["vehicle"].append(_number(service.get("vehicle")))
            engine = service.get("snapshot") or ()
            rows["stops"].append(_number(engine[10]) if len(engine) > 10 else None)
        series.append(
            dict(
                scope=head.get("route_id") or f"service-{index + 1}",
                label=f"Service {index + 1}",
                dates=dates,
                elapsed=elapsed,
                **rows,
            )
        )
    return series


def _network_series(series: list[dict]) -> dict | None:
    """Combine per-service series into a network series when counters align."""
    if not series:
        return None
    combined = dict(
        scope="network",
        label="Network",
        dates=series[0]["dates"],
        elapsed=series[0]["elapsed"],
    )
    for name in ("delivered", "waiting", "cargo_load", "capacity"):
        combined[name] = [
            _complete_sum([row[name][i] for row in series]) for i in range(len(series[0][name]))
        ]
    combined["stops"] = [None] * len(series[0]["delivered"])
    combined["vehicle"] = [None] * len(series[0]["delivered"])
    return combined


def _episodes(delivered: list, elapsed: list) -> list[dict]:
    """Coalesce consecutive positive delivered-cargo increments into episodes.

    Positive increments with no intervening non-positive sample belong to one
    episode; any flat, non-positive or missing sample separates episodes. They
    are coalesced batches, not individual trips.
    """
    episodes: list[dict] = []
    last_positive = None
    for index in range(1, len(delivered)):
        current, before = delivered[index], delivered[index - 1]
        if current is None or before is None:
            continue
        delta = current - before
        if delta <= 0:
            continue
        if last_positive is None or index - last_positive > 1:
            episodes.append(
                dict(
                    index=index,
                    start_elapsed=elapsed[index] if elapsed[index] is not None else None,
                    cargo=delta,
                )
            )
        else:
            episodes[-1]["cargo"] += delta
        last_positive = index
    return episodes


def _spacing_days(episodes: list[dict]) -> tuple[int | None, int | None]:
    starts = [item["start_elapsed"] for item in episodes]
    gaps = [b - a for a, b in zip(starts, starts[1:]) if a is not None and b is not None]
    return (min(gaps), max(gaps)) if gaps else (None, None)


def _growth_ratio(values: list) -> float | None:
    """Deterministic first-half/second-half mean growth over retained samples."""
    present = [v for v in values if v is not None]
    if len(present) < 8:
        return None
    middle = len(present) // 2
    first, second = present[:middle], present[middle:]
    mean_first = sum(first) / len(first)
    if mean_first <= 0:
        return None
    return round((sum(second) / len(second)) / mean_first, 6)


def _series_span(series: dict) -> str:
    dates = [date for date in series.get("dates", []) if date is not None]
    if not dates:
        return "series observation window not recorded"
    return f"series economy dates {min(dates)}..{max(dates)}"


def bottleneck_assessment(series: dict, source_ref: str) -> BottleneckAssessment:
    """Classify a retained series; a hypothesis, never a proven cause."""
    delivered, waiting = series["delivered"], series["waiting"]
    samples = len(delivered)
    evidence_base = f"source {source_ref}"
    if samples < 3 or sum(v is not None for v in waiting) == 0:
        return BottleneckAssessment(
            scope=series["scope"],
            label=series["label"],
            classification="INSUFFICIENT_DATA",
            status="UNKNOWN",
            data_status="INSUFFICIENT_DATA",
            observations={},
            evidence=[evidence_base],
            reasoning="Too few retained samples with waiting-cargo observations.",
            missing_information=["Retained snapshots with waiting-cargo samples."],
        )
    waiting_present = sum(v is not None for v in waiting)
    positive = sum(1 for v in waiting if v is not None and v > 0)
    positive_fraction = round(positive / waiting_present, 6)
    episodes = _episodes(delivered, series["elapsed"])
    spacing_min, spacing_max = _spacing_days(episodes)
    growth = _growth_ratio(waiting)
    paired = [
        (load, capacity)
        for load, capacity in zip(series["cargo_load"], series["capacity"])
        if load is not None and capacity
    ]
    full_load_fraction = (
        round(sum(1 for load, capacity in paired if load == capacity) / len(paired), 6)
        if paired
        else None
    )
    loads = [v for v in series["cargo_load"] if v is not None]
    zero_load_fraction = (
        round(sum(1 for load in loads if load == 0) / len(loads), 6) if loads else None
    )
    stops = [v for v in series.get("stops", []) if v is not None]
    stopped_fraction = (
        round(sum(1 for speed in stops if speed == 0) / len(stops), 6) if stops else None
    )
    observations: dict[str, Any] = {
        "delivered_samples": samples,
        "waiting_samples": waiting_present,
        "endpoint_waiting_units": waiting[-1],
        "maximum_sampled_waiting_units": max(v for v in waiting if v is not None),
        "waiting_growth_ratio": growth,
        "positive_waiting_fraction": positive_fraction,
        "full_load_sample_fraction": full_load_fraction,
        "zero_load_sample_fraction": zero_load_fraction,
        "stopped_sample_fraction": stopped_fraction,
        "unloading_episodes": len(episodes),
        "episode_spacing_min_days": spacing_min,
        "episode_spacing_max_days": spacing_max,
    }
    if growth is not None and growth > 1.2:
        classification = "GROWING_BACKLOG_SAMPLE_HYPOTHESIS"
        reasoning = (
            f"Late-window mean waiting cargo exceeds the early-window mean by {growth}x, "
            "so backlog may be growing relative to service effectiveness. This is a "
            "sampling hypothesis, not a proven cause: fluctuating queues cannot bound "
            "cumulative production or lost cargo."
        )
    elif episodes and positive_fraction >= 0.5:
        classification = "CAPACITY_BOTTLENECK_HYPOTHESIS"
        reasoning = (
            f"Waiting cargo is present in {positive} of {waiting_present} samples and "
            "unloading episodes recur, so effective carrying capacity or dispatch "
            "frequency may be insufficient relative to available station cargo. This is a "
            "hypothesis, not a proven causal result."
        )
    elif positive_fraction < 0.5:
        classification = "NO_SUSTAINED_BACKLOG_OBSERVED"
        reasoning = "Waiting cargo is absent from most retained samples."
    else:
        classification = "INSUFFICIENT_DATA"
        reasoning = "Retained samples do not support a backlog classification."
    status = (
        "UNKNOWN"
        if classification == "INSUFFICIENT_DATA"
        else ("DERIVED" if classification == "NO_SUSTAINED_BACKLOG_OBSERVED" else "HYPOTHESIS")
    )
    return BottleneckAssessment(
        scope=series["scope"],
        label=series["label"],
        classification=classification,
        status=status,
        data_status="SUFFICIENT",
        observations=observations,
        evidence=[evidence_base, _series_span(series)],
        reasoning=reasoning,
        missing_information=list(_BOTTLENECK_MISSING),
    )


def _batch_evidence_bottlenecks(evaluation: dict, source_ref: str) -> list[BottleneckAssessment]:
    """Network evaluations retain endpoint batch measurements, not series."""
    classification = "NO_SERIES_IN_RETAINED_BATCH_EVIDENCE"
    records: list[BottleneckAssessment] = []
    for position, service in enumerate(evaluation.get("services") or [], 1):
        waiting = next(
            (
                _number(metric["actual"])
                for metric in service.get("metrics", [])
                if metric["name"] == "source_waiting" and metric.get("actual") is not None
            ),
            None,
        )
        records.append(
            BottleneckAssessment(
                scope=service.get("route_id") or f"service-{position}",
                label=f"Service {position}",
                classification=classification,
                status="UNKNOWN",
                data_status="INSUFFICIENT_DATA",
                observations={"endpoint_source_waiting_units": waiting},
                evidence=[f"source {source_ref}"],
                reasoning="Network evaluation batches are endpoint measurements; no "
                "per-snapshot series is retained for bottleneck detection. Continuous P07 "
                "reporting is required for series-level analysis.",
                missing_information=["Retained snapshot series for this batch."],
            )
        )
    records.append(
        BottleneckAssessment(
            scope="network",
            label="Network",
            classification=classification,
            status="UNKNOWN",
            data_status="INSUFFICIENT_DATA",
            observations={},
            evidence=[f"source {source_ref}"],
            reasoning="Serial single-service batches cannot be combined into a network "
            "series without inventing a common observation window.",
            missing_information=["A common network observation window with series."],
        )
    )
    return records


# ---------------------------------------------------------------------------
# Metric declarations
# ---------------------------------------------------------------------------


def _metric(
    name: str,
    unit: str,
    status: str,
    value,
    observation_period: str,
    source: str,
    derivation: str,
    missing_data_behavior: str,
    limitations: str = "",
) -> DeclaredMetric:
    if value is None and status in {"OBSERVED", "DERIVED"}:
        status = "UNKNOWN"
    return DeclaredMetric(
        name=name,
        unit=unit,
        status=status,
        value=value if status != "UNKNOWN" else None,
        observation_period=observation_period,
        source=source,
        derivation=derivation,
        missing_data_behavior=missing_data_behavior,
        limitations=limitations,
    )


def _metric_value(metrics: list[DeclaredMetric], *names) -> int | float | None:
    for name in names:
        metric = next((m for m in metrics if m.name == name and m.status != "UNKNOWN"), None)
        if metric is not None and metric.value is not None:
            return metric.value
    return None


def _network_metric(metrics: list[DeclaredMetric], *names) -> DeclaredMetric | None:
    """Resolve a network-level metric among candidate names, in priority order.

    Continuous documents repeat names like ``delivered_cargo`` per service while
    network roll-ups carry distinct names; the first candidate that exists wins
    (an existing UNKNOWN also wins, so lookups never fall back onto a
    service-level entry) and the overall result is None when it is UNKNOWN.
    """
    for name in names:
        metric = next((m for m in metrics if m.name == name), None)
        if metric is not None:
            return None if metric.status == "UNKNOWN" else metric
    return None


def _rate(total, days) -> int | float | None:
    if total is None or days is None or days <= 0:
        return None
    value = total / days
    return int(value) if value == int(value) else round(float(value), 6)


def _ranks(services: list[ServicePerformance]) -> dict[str, int]:
    scored = []
    for service in services:
        value = _metric_value(service.metrics, "cargo_per_economy_day")
        if value is not None:
            scored.append((service.scope, value))
    scored.sort(key=lambda row: (-row[1], row[0]))
    ranks: dict[str, int] = {}
    previous_value, previous_rank = None, 0
    for position, (scope, value) in enumerate(scored, 1):
        rank = previous_rank if value == previous_value else position
        ranks[scope] = rank
        previous_value, previous_rank = value, rank
    return ranks


# ---------------------------------------------------------------------------
# Continuous builder
# ---------------------------------------------------------------------------


def _service_metrics(entry: dict, totals: dict, period: str, source_ref: str):
    """Declare per-service metrics from series, endpoint counters and totals."""
    delivered, waiting, elapsed = entry["delivered"], entry["waiting"], entry["elapsed"]
    scope = entry["scope"]
    source = f"{source_ref} snapshots · scope {scope}"
    endpoint = delivered[-1] if delivered else None
    opening = delivered[0] if delivered else None
    delta = endpoint - opening if endpoint is not None and opening is not None else None
    days = None
    if elapsed and elapsed[-1] is not None and elapsed[0] is not None:
        window_days = elapsed[-1] - elapsed[0]
        days = window_days if window_days > 0 else None
    cargo_day = _rate(delta, days)
    episodes = _episodes(delivered, elapsed)
    spacing_min, spacing_max = _spacing_days(episodes)
    waiting_present = sum(1 for v in waiting if v is not None)
    positive_waiting = (
        round(sum(1 for v in waiting if v is not None and v > 0) / waiting_present, 6)
        if waiting_present
        else None
    )
    paired = [
        (load, capacity)
        for load, capacity in zip(entry["cargo_load"], entry["capacity"])
        if load is not None and capacity
    ]
    full_load = (
        round(sum(1 for load, capacity in paired if load == capacity) / len(paired), 6)
        if paired
        else None
    )
    loads = [v for v in entry["cargo_load"] if v is not None]
    zero_load = round(sum(1 for v in loads if v == 0) / len(loads), 6) if loads else None
    vehicle_ids = {int(v) for v in entry["vehicle"] if v is not None}
    vehicle_count = len(vehicle_ids) or None
    final_date = entry["dates"][-1] if entry["dates"] else None
    service_revenue = _number(totals.get("revenue"))
    return [
        _metric(
            "delivered_cargo",
            "cargo_units",
            "DERIVED" if delta is not None else "UNKNOWN",
            delta,
            period,
            source,
            "Difference of the native cumulative delivered-cargo counter at window endpoints.",
            "Both endpoint counters must be retained; otherwise the window delta stays UNKNOWN "
            "while the endpoint value itself stays OBSERVED.",
        ),
        _metric(
            "cumulative_delivered_cargo",
            "cargo_units",
            "OBSERVED" if endpoint is not None else "UNKNOWN",
            endpoint,
            f"up to economy date {_fmt(final_date)}",
            source,
            "Native cumulative delivered-cargo counter at the final retained snapshot.",
            "UNKNOWN when the final snapshot is missing.",
        ),
        _metric(
            "cargo_per_economy_day",
            "cargo_units/economy_day",
            "DERIVED",
            cargo_day,
            period,
            "delivered_cargo / observed service window days",
            "Window delta divided by the endpoint economy-date difference.",
            "UNKNOWN without two dated endpoint samples.",
            "Includes serial setup and waiting; not steady-state throughput.",
        ),
        _metric(
            "unloading_episodes",
            "episodes",
            "DERIVED" if sum(1 for v in delivered if v is not None) >= 2 else "UNKNOWN",
            len(episodes) if sum(1 for v in delivered if v is not None) >= 2 else None,
            period,
            "coalesced positive delivered-cargo increments",
            "Groups consecutive snapshots with positive delivered deltas; group size is the "
            "coalesced batch, not individual partial snapshots.",
            "UNKNOWN without at least two delivered samples; zero episodes is not stated "
            "from a single sample.",
            "Derived observed episodes; spacing is approximate delivery cadence.",
        ),
        _metric(
            "episode_spacing_min_days",
            "economy_days",
            "DERIVED" if spacing_min is not None else "UNKNOWN",
            spacing_min,
            period,
            "episode start spacing in snapshot elapsed economy days",
            "Minimum gap between consecutive episode starts.",
            "Needs at least two datable episodes.",
        ),
        _metric(
            "episode_spacing_max_days",
            "economy_days",
            "DERIVED" if spacing_max is not None else "UNKNOWN",
            spacing_max,
            period,
            "episode start spacing in snapshot elapsed economy days",
            "Maximum gap between consecutive episode starts.",
            "Needs at least two datable episodes.",
        ),
        _metric(
            "sampled_backlog_end_units",
            "cargo_units",
            "OBSERVED" if waiting and waiting[-1] is not None else "UNKNOWN",
            waiting[-1] if waiting else None,
            f"at final sample economy date {_fmt(final_date)}",
            source,
            "Native station waiting-cargo point sample at the final retained snapshot.",
            "Point sample; backlog is not unmet demand.",
        ),
        _metric(
            "sampled_backlog_max_units",
            "cargo_units",
            "OBSERVED" if waiting and waiting_present else "UNKNOWN",
            max((v for v in waiting if v is not None), default=None),
            period,
            source,
            "Maximum waiting-cargo point sample in the retained window.",
            "Point samples only; fluctuating queues cannot bound lost cargo.",
        ),
        _metric(
            "positive_waiting_fraction",
            "ratio",
            "DERIVED" if positive_waiting is not None else "UNKNOWN",
            positive_waiting,
            period,
            "waiting-cargo samples > 0 / samples with waiting observations",
            "Fraction of retained samples with nonzero waiting cargo.",
            "UNKNOWN when no waiting samples are retained; never substituted by zero.",
        ),
        _metric(
            "full_load_sample_fraction",
            "ratio",
            "DERIVED" if full_load is not None else "UNKNOWN",
            full_load,
            period,
            "cargo_load == capacity per retained sample",
            "Fraction of samples whose measured load equals measured capacity.",
            "Requires load and capacity in the same samples; never inferred.",
            "Point samples; not time-weighted utilization.",
        ),
        _metric(
            "zero_load_sample_fraction",
            "ratio",
            "DERIVED" if zero_load is not None else "UNKNOWN",
            zero_load,
            period,
            "cargo_load == 0 per retained sample",
            "Fraction of samples whose measured load is zero (may include empty return travel).",
            "Requires load samples; UNKNOWN is not zero.",
        ),
        _metric(
            "service_revenue",
            "GBP",
            "DERIVED" if service_revenue is not None else "UNKNOWN",
            service_revenue,
            period,
            f"{source_ref} totals[scope={scope}].revenue",
            "Revenue attributed to this service where the retained evidence supplies it.",
            "Where service revenue was null it stays UNKNOWN; company income is never "
            "redistributed across services by cargo share or vehicle profit.",
            "Company income cannot be split without inventing attribution.",
        ),
        _metric(
            "cargo_per_vehicle",
            "cargo_units/vehicle",
            "DERIVED" if delta is not None and vehicle_count else "UNKNOWN",
            delta / vehicle_count if delta is not None and vehicle_count else None,
            period,
            "delivered cargo window delta / distinct observed vehicle IDs",
            "Service window delta divided by the observed vehicle count.",
            "UNKNOWN when vehicle identity is absent or the delta is incomplete.",
        ),
        _metric(
            "service_window_days",
            "economy_days",
            "DERIVED" if days is not None else "UNKNOWN",
            days,
            period,
            "snapshot elapsed-economy-day endpoint difference",
            "Elapsed economy days spanned by the retained samples for this scope.",
            "Needs dated endpoints.",
        ),
    ], cargo_day


def _continuous_window(report: dict) -> dict[str, int | None]:
    snapshots = report.get("snapshots") or []
    opening, final = snapshots[0], snapshots[-1]
    start, end = opening.get("economy_date"), final.get("economy_date")
    days = end - start if start is not None and end is not None else None
    return {"start_economy_date": start, "end_economy_date": end, "economy_days": days}


def _finance_metrics(finance: dict, period: str, source_ref: str) -> list[DeclaredMetric]:
    revenue = _number(finance.get("freight_revenue"))
    capex = _number(finance.get("capex"))
    opening_cash = _number(finance.get("opening_cash"))
    closing_cash = _number(finance.get("closing_cash"))
    aggregate_expenses = _number(finance.get("known_unallocated_expenses"))
    unattributed = _number(finance.get("unknown_cash_movements"))
    vehicle_opex = _number(finance.get("vehicle_operating_expenses"))
    operating_profit = _number(finance.get("operating_profit"))
    roi = _number(finance.get("roi"))
    net_flow = (
        closing_cash - opening_cash
        if closing_cash is not None and opening_cash is not None
        else None
    )
    basis = f"{source_ref} finance reconciliation of native quarter counters and receipts."
    return [
        _metric(
            "observed_gross_revenue",
            "GBP",
            "OBSERVED" if revenue is not None else "UNKNOWN",
            revenue,
            period,
            basis,
            "Company gross income attributed to freight delivery in the retained reconciliation.",
            "UNKNOWN when no revenue counter was retained; UNKNOWN is never zero.",
            "Gross company income, not profit; expense attribution decides the rest.",
        ),
        _metric(
            "observed_capex",
            "GBP",
            "OBSERVED" if capex is not None else "UNKNOWN",
            capex,
            "construction-to-operation setup window",
            f"Verified construction and purchase receipts bound to the attempt ({source_ref}).",
            "Native command accounting; CAPEX is counted once, outside the operating window.",
            "Residual asset value, depreciation and world preparation are excluded.",
        ),
        _metric(
            "opening_cash",
            "GBP",
            "OBSERVED" if opening_cash is not None else "UNKNOWN",
            opening_cash,
            "operation-start snapshot",
            basis,
            "Native company cash at the operating boundary.",
            "UNKNOWN when the opening snapshot is missing.",
        ),
        _metric(
            "closing_cash",
            "GBP",
            "OBSERVED" if closing_cash is not None else "UNKNOWN",
            closing_cash,
            f"final sampler economy-date window: {period}",
            basis,
            "Native company cash at the last retained snapshot.",
            "UNKNOWN when the closing snapshot is missing.",
        ),
        _metric(
            "net_cash_flow",
            "GBP",
            "DERIVED",
            net_flow,
            period,
            "closing_cash - opening_cash",
            "Observed company cash movement across the operating window.",
            "UNKNOWN without both endpoint balances.",
        ),
        _metric(
            "observed_aggregate_expenses",
            "GBP",
            "DERIVED",
            aggregate_expenses,
            period,
            basis,
            "Signed sum of native company aggregate expense counters (categories unallocated).",
            "UNKNOWN where no expense counters were retained; UNKNOWN is not zero.",
            "Company aggregate; not attributed OPEX categories.",
        ),
        _metric(
            "vehicle_operating_expenses",
            "GBP",
            "OBSERVED" if vehicle_opex is not None else "UNKNOWN",
            vehicle_opex,
            period,
            basis,
            "Attributed vehicle operating expenses where the native evidence supplies them.",
            "Missing attribution keeps this UNKNOWN; unknown is never treated as zero.",
            "Vehicle profit deltas and running-cost rates do not establish actual OPEX.",
        ),
        _metric(
            "unattributed_cash_movement",
            "GBP",
            "DERIVED",
            unattributed,
            period,
            basis,
            "Residual of the reconciled company cash identity after all known movements.",
            "UNKNOWN when the identity cannot be reconciled.",
            "Residual movement is not renamed into an expense category.",
        ),
        _metric(
            "operating_profit",
            "GBP",
            "OBSERVED" if operating_profit is not None else "UNKNOWN",
            operating_profit,
            period,
            basis,
            "Revenue minus complete known costs; declared only when expense classification "
            "is complete.",
            "Never derived from revenue minus an incomplete subset of costs.",
        ),
        _metric(
            "roi",
            "ratio",
            "OBSERVED" if roi is not None else "UNKNOWN",
            roi,
            period,
            basis,
            "(revenue - known costs) / capex; declared only when classification is complete.",
            "Never derived from revenue minus an incomplete subset of costs.",
        ),
    ]


def _interval_series(report: dict) -> list[IntervalPoint]:
    rows = []
    for row in report.get("periods") or []:
        if row.get("scope") != "network":
            continue
        rows.append(
            IntervalPoint(
                period=str(row["period"]),
                index=int(row["index"]),
                scope="network",
                start_economy_date=int(row["start_economy_date"]),
                end_economy_date=int(row["end_economy_date"]),
                elapsed_economy_days=_number(row.get("elapsed_economy_days")),
                revenue=_number(row.get("revenue")),
                delivered_cargo=_number(row.get("delivered_cargo")),
                known_unallocated_expenses=_number(row.get("known_unallocated_expenses")),
            )
        )
    return rows


def _time_series(series: list[dict]) -> dict[str, list[SeriesPoint]]:
    points: dict[str, list[SeriesPoint]] = {}
    entries = list(series)
    network = _network_series(series) if series else None
    if network is not None:
        entries.append(network)
    for entry in entries:
        count = len(entry["delivered"])
        sampled = list(range(count))
        if count > MAX_SERIES_POINTS:
            stride = -(-count // MAX_SERIES_POINTS)
            sampled = [index for index in sampled if index % stride == 0]
            if sampled[-1] != count - 1:
                sampled.append(count - 1)
        points[entry["scope"]] = [
            SeriesPoint(
                economy_date=int(entry["dates"][index]),
                delivered=entry["delivered"][index],
                waiting=_number(entry["waiting"][index]),
                cargo_load=_number(entry["cargo_load"][index]),
                capacity=_number(entry["capacity"][index]),
            )
            for index in sampled
        ]
    return dict(sorted(points.items()))


def bottleneck_recommendations(
    bottlenecks: list[BottleneckAssessment],
) -> list[AdvisoryRecommendation]:
    """Determine advisory recommendations from bottleneck assessments only."""
    rows: list[AdvisoryRecommendation] = []
    for assessment in bottlenecks:
        scope, observations = assessment.scope, assessment.observations
        evidence = list(assessment.evidence)
        deviates = assessment.classification in {
            "CAPACITY_BOTTLENECK_HYPOTHESIS",
            "GROWING_BACKLOG_SAMPLE_HYPOTHESIS",
        }
        if deviates:
            code = (
                "capacity_bottleneck_candidate"
                if assessment.classification == "CAPACITY_BOTTLENECK_HYPOTHESIS"
                else "backlog_recovery_candidate"
            )
            rows.append(
                AdvisoryRecommendation(
                    recommendation_id="",
                    code=code,
                    scope=scope,
                    confidence="HYPOTHESIS",
                    reason=(
                        f"{assessment.label} shows {assessment.classification}: endpoint "
                        f"waiting {_fmt(observations.get('endpoint_waiting_units'))} units, "
                        f"{observations.get('unloading_episodes')} recurring unloading "
                        f"episodes, positive waiting fraction "
                        f"{_fmt(observations.get('positive_waiting_fraction'))}."
                    ),
                    evidence=evidence,
                    expected_improvement_direction=(
                        "More effective carrying capacity or dispatch frequency for this "
                        "service may reduce waiting cargo; the improvement is not measured."
                    ),
                    advisory_only=True,
                    missing_information=list(_BOTTLENECK_MISSING)
                    + ["No complete expense attribution to rank net returns."],
                    suggested_next_experiment=_CAPACITY_EXPERIMENT_TEXT,
                )
            )
        growth = observations.get("waiting_growth_ratio")
        if growth is not None and growth > 1.2:
            rows.append(
                AdvisoryRecommendation(
                    recommendation_id="",
                    code="backlog_growth_watch",
                    scope=scope,
                    confidence="HYPOTHESIS",
                    reason=(
                        f"Waiting-cargo samples grow across the window with growth ratio {growth}."
                    ),
                    evidence=evidence,
                    expected_improvement_direction=(
                        "Additional capacity or frequency may flatten sampled growth; unproven."
                    ),
                    advisory_only=True,
                    missing_information=[
                        "Cumulative production and lost cargo are not observable."
                    ],
                    suggested_next_experiment=_CAPACITY_EXPERIMENT_TEXT,
                )
            )
        zero_load = observations.get("zero_load_sample_fraction")
        spacing = observations.get("episode_spacing_max_days")
        if zero_load is not None and zero_load >= 0.4 and spacing is not None and spacing >= 30:
            rows.append(
                AdvisoryRecommendation(
                    recommendation_id="",
                    code="vehicle_idle_review",
                    scope=scope,
                    confidence="HYPOTHESIS",
                    reason=(
                        f"Zero-load samples reach {zero_load} of the window with episode "
                        f"spacing up to {spacing} economy days; empty load includes return "
                        "travel, so this is not proven avoidable idle time."
                    ),
                    evidence=evidence,
                    expected_improvement_direction=(
                        "Route or cadence review may reduce unproductive travel; unproven."
                    ),
                    advisory_only=True,
                    missing_information=["No departure/arrival durations; no occupancy counters."],
                    suggested_next_experiment=_ROUTING_EXPERIMENT_TEXT,
                )
            )
        positive_waiting = observations.get("positive_waiting_fraction")
        if (
            positive_waiting is not None
            and positive_waiting >= 0.5
            and spacing is not None
            and spacing >= 30
        ):
            rows.append(
                AdvisoryRecommendation(
                    recommendation_id="",
                    code="vehicle_frequency_candidate",
                    scope=scope,
                    confidence="HYPOTHESIS",
                    reason=(
                        f"Recurring episodes spaced up to {spacing} economy days with "
                        "persistent waiting cargo suggest a frequency and fleet-size "
                        "trade-off candidate."
                    ),
                    evidence=evidence,
                    expected_improvement_direction=(
                        "Higher dispatch frequency may raise delivered cargo per economy day; "
                        "unproven and not a demand forecast."
                    ),
                    advisory_only=True,
                    missing_information=[
                        "No demand/production counter; no repeat-trip cost series."
                    ],
                    suggested_next_experiment=_FREQUENCY_EXPERIMENT_TEXT,
                )
            )
    return rows


def _finance_recommendations(finance: dict) -> list[AdvisoryRecommendation]:
    revenue = _number(finance.get("freight_revenue"))
    capex = _number(finance.get("capex"))
    vehicle_opex = _number(finance.get("vehicle_operating_expenses"))
    unattributed = _number(finance.get("unknown_cash_movements"))
    aggregate = _number(finance.get("known_unallocated_expenses"))
    rows: list[AdvisoryRecommendation] = []
    generic_missing = ["Retained evidence limitations of this evaluation."]
    if capex and revenue and revenue / capex < 1:
        rows.append(
            AdvisoryRecommendation(
                recommendation_id="",
                code="revenue_to_capex_review",
                scope="network",
                confidence="DERIVED",
                reason=(
                    f"Window revenue £{revenue} is below measured CAPEX £{capex}; revenue is "
                    "timing-dependent and serial batches are step-wise, so this does not "
                    "establish profitability, a payback or a forecast."
                ),
                evidence=["window revenue totals", "verified CAPEX receipts"],
                expected_improvement_direction=(
                    "Collect repeat-batch revenue and complete attributed expenses before "
                    "judging capital recovery; direction is unmeasured."
                ),
                advisory_only=True,
                missing_information=["Full operating expenses remain unattributed."],
                suggested_next_experiment=(
                    "Replay existing P07 evidence offline and collect attributed expenses "
                    "across matching windows before cost-driven ranking."
                ),
            )
        )
    if revenue and vehicle_opex is None:
        rows.append(
            AdvisoryRecommendation(
                recommendation_id="",
                code="expense_attribution_gap",
                scope="network",
                confidence="DERIVED",
                reason="Retained evidence has revenue but no complete attributed vehicle "
                "operating expenses for the same windows.",
                evidence=["window revenue totals"],
                expected_improvement_direction=(
                    "None measurable; the gap blocks cost-driven optimization inputs."
                ),
                advisory_only=True,
                missing_information=["Itemized OPEX categories; financing attribution."],
                suggested_next_experiment=(
                    "Extend the native observation contract to retain matched expense "
                    "windows before ranking net returns."
                ),
            )
        )
    if unattributed not in (None, 0):
        rows.append(
            AdvisoryRecommendation(
                recommendation_id="",
                code="unattributed_cash_movement",
                scope="network",
                confidence="DERIVED",
                reason=f"£{unattributed} of company cash movement remains unattributed after "
                "all known movements; unallocated decreases do not establish categories.",
                evidence=["finance reconciliation residual"],
                expected_improvement_direction="None measurable; blocking clean attribution.",
                advisory_only=True,
                missing_information=["Native expense-category counters for the residual."],
                suggested_next_experiment=(
                    "Capture expense categories in the next authorized observation window."
                ),
            )
        )
    if aggregate not in (None, 0):
        rows.append(
            AdvisoryRecommendation(
                recommendation_id="",
                code="aggregate_expense_allocation",
                scope="network",
                confidence="DERIVED",
                reason=f"Observed company aggregate expenses of £{aggregate} are unallocated "
                "across categories, so cost trends stay aggregate-only.",
                evidence=["signed company aggregate expense counters"],
                expected_improvement_direction=(
                    "None measurable; category split required before OPEX-sensitive work."
                ),
                advisory_only=True,
                missing_information=generic_missing + ["Per-category counters over windows."],
                suggested_next_experiment="Extend the observation contract with category counters.",
            )
        )
    return rows


def _sorted_recommendations(
    rows: list[AdvisoryRecommendation],
) -> list[AdvisoryRecommendation]:
    """Deterministic order and stable identifiers for equal inputs."""
    ordered = sorted(rows, key=lambda row: (row.code, row.scope, row.reason))
    return [
        row.model_copy(update={"recommendation_id": f"rec-{index:03d}-{row.code}"})
        for index, row in enumerate(ordered, 1)
    ]


def build_continuous_insights(
    report: dict,
    *,
    source_ref: str = "controlled input",
    source_sha256: str | None = None,
    world_identity: dict[str, str] | None = None,
) -> PerformanceInsights:
    """Build performance insights from a P07 continuous summary document."""
    snapshots = report.get("snapshots") or []
    if not snapshots:
        raise ValueError("continuous summary has no snapshots")
    window = _continuous_window(report)
    days = window["economy_days"]
    period = (
        f"economy dates {window['start_economy_date']}..{window['end_economy_date']} "
        f"({days} days, {len(snapshots)} samples)"
        if days is not None
        else "retained sampled window"
    )
    totals = {row["scope"]: row for row in report.get("totals") or []}
    network_total = totals.get("network") or {}
    finance = report.get("finance") or {}
    series = _service_series(report)
    if not series:
        raise ValueError("continuous summary has no per-service series")
    metrics: list[DeclaredMetric] = []
    services: list[ServicePerformance] = []
    for entry in series:
        route_metrics, _ = _service_metrics(
            entry, totals.get(entry["scope"], {}), period, source_ref
        )
        metrics.extend(route_metrics)
        vehicle = next((int(v) for v in entry["vehicle"] if v is not None), None)
        services.append(
            ServicePerformance(
                scope=entry["scope"],
                label=entry["label"],
                vehicle=vehicle,
                metrics=route_metrics,
            )
        )
    bottleneck_entries = [bottleneck_assessment(entry, source_ref) for entry in series]
    network_series = _network_series(series)
    if network_series is not None:
        bottleneck_entries.append(bottleneck_assessment(network_series, source_ref))
    endpoint_deltas = []
    for entry in series:
        endpoint, opening = entry["delivered"][-1], entry["delivered"][0]
        endpoint_deltas.append(
            endpoint - opening if endpoint is not None and opening is not None else None
        )
    delivered_total = _number(network_total.get("delivered_cargo"))
    if delivered_total is None:
        delivered_total = _complete_sum(endpoint_deltas)
    revenue_total = _number(network_total.get("revenue"))
    vehicle_ids = {int(v) for entry in series for v in entry["vehicle"] if v is not None}
    vehicle_count = len(vehicle_ids) or None
    # Network episode count is only meaningful when every service series was
    # assessable; otherwise a total would silently partially sum.
    episode_counts = [
        assessment.observations.get("unloading_episodes")
        for assessment in bottleneck_entries
        if assessment.scope != "network"
    ]
    episodes_total = (
        sum(episode_counts)
        if episode_counts and all(count is not None for count in episode_counts)
        else None
    )
    metrics.extend(
        [
            _metric(
                "network_delivered_cargo",
                "cargo_units",
                "DERIVED",
                delivered_total,
                period,
                f"{source_ref} totals[scope=network]",
                "Window sum of per-service native cumulative counter deltas.",
                "UNKNOWN when any service endpoint delta is missing; never partially summed.",
            ),
            _metric(
                "network_revenue",
                "GBP",
                "DERIVED" if revenue_total is not None else "UNKNOWN",
                revenue_total,
                period,
                f"{source_ref} totals[scope=network].revenue",
                "Sum of native company quarter-income deltas across the window; company "
                "level, not per-service.",
                "Service-attributed revenue stays UNKNOWN where null; company income is "
                "never redistributed across services.",
                "Includes non-service company income.",
            ),
            _metric(
                "network_cargo_per_economy_day",
                "cargo_units/economy_day",
                "DERIVED",
                _rate(delivered_total, days),
                period,
                "delivered_cargo / window economy days",
                "Window total over the endpoint economy-date difference.",
                "UNKNOWN when endpoints are incomplete.",
                "Includes serial setup and waiting; not steady-state throughput.",
            ),
            _metric(
                "network_revenue_per_economy_day",
                "GBP/economy_day",
                "DERIVED",
                _rate(revenue_total, days),
                period,
                "network_revenue / window economy days",
                "Window revenue over the endpoint economy-date difference.",
                "UNKNOWN when endpoints are incomplete or days are zero.",
            ),
            _metric(
                "observed_active_vehicles",
                "vehicles",
                "DERIVED" if vehicle_count is not None else "UNKNOWN",
                vehicle_count,
                period,
                "distinct native vehicle IDs across service snapshot readbacks",
                "Count of distinct vehicle identifiers seen in sampled service readbacks.",
                "Vehicles never sampled remain uncounted.",
            ),
            _metric(
                "delivery_frequency",
                "episodes/30_economy_days",
                "DERIVED",
                round(episodes_total / days * 30, 6) if days and episodes_total else None,
                period,
                "coalesced unloading episodes across assessable services",
                "Episode count per 30 economy days across all services; every service "
                "series must be assessable, otherwise the total stays UNKNOWN instead "
                "of partially summing.",
                "UNKNOWN when any service series lacks an episode count or endpoints "
                "are undated; never partially summed.",
                "Not a dispatch cadence for a differently configured topology.",
            ),
        ]
    )
    metrics.extend(_finance_metrics(finance, period, source_ref))
    ranks = _ranks(services)
    services = [
        service.model_copy(update={"rank_by_cargo_per_day": ranks.get(service.scope)})
        for service in services
    ]
    rows = bottleneck_recommendations(
        [b for b in bottleneck_entries if b.scope != "network"]
    ) + _finance_recommendations(finance)
    native_terminal = None
    recovery = report.get("offline_recovery")
    if recovery is not None:
        status = (recovery.get("original_terminal") or {}).get("status")
        if status:
            native_terminal = f"{status} (historical native terminal; metadata derived offline)"
        else:
            native_terminal = "historical native terminal status UNKNOWN (metadata derived offline)"
    service_limits = [
        "Service revenue attribution stays UNKNOWN where retained service revenue was null.",
    ]
    return PerformanceInsights(
        schema_version=SCHEMA_VERSION,
        classification=str(report.get("classification", "UNKNOWN_CLASSIFICATION")),
        source_kind="continuous",
        source_ref=source_ref,
        source_sha256=source_sha256,
        native_terminal_status=native_terminal,
        world_identity=world_identity,
        observation_window={
            "start_economy_date": window["start_economy_date"],
            "end_economy_date": window["end_economy_date"],
            "economy_days": days,
            "samples": len(snapshots),
        },
        metrics=metrics,
        services=services,
        time_series=_time_series(series),
        interval_series=_interval_series(report),
        bottlenecks=bottleneck_entries,
        recommendations=_sorted_recommendations(rows),
        limitations=list(_BASE_LIMITATIONS)
        + list(report.get("limitations") or [])
        + service_limits,
        financial_attribution=_financial_attribution_status(report),
    )


# ---------------------------------------------------------------------------
# Network-evaluation builder (fixed demo)
# ---------------------------------------------------------------------------


_FEEDBACK_DIRECTION = {
    "cost_estimation_error": (
        "Align P08 candidate estimates with observed command quotes before any "
        "cost-driven optimization."
    ),
    "batch_capacity_utilization": (
        "Compare batch size against selected fleet capacity; repeat-trip observation "
        "is required before resizing fleets."
    ),
    "source_waiting_backlog": (
        "Measure repeat-trip queue growth and service frequency before expanding capacity."
    ),
    "collect_opex": (
        "Collect complete attributed expenses over matching windows before ranking net returns."
    ),
    "validate_shared_assets": (
        "Validate paid shared-asset reuse with unique construction ledgers."
    ),
    "validate_concurrency": (
        "Validate simultaneous services before serial batches inform capacity planning."
    ),
}


def build_network_insights(
    evaluation: dict,
    *,
    source_ref: str = "controlled input",
    source_sha256: str | None = None,
    world_identity: dict[str, str] | None = None,
) -> PerformanceInsights:
    """Build performance insights from a P07 network evaluation document."""
    if not evaluation.get("metrics") and not evaluation.get("services"):
        raise ValueError("evaluation document lacks network metrics and services")
    economy = evaluation.get("game_time") or {}
    days = economy.get("total_elapsed_economy_days")
    period = f"serial batch window ({days} economy days)" if days else "serial batch window"
    metrics: list[DeclaredMetric] = [
        _metric(
            "operation_window_days",
            "economy_days",
            "OBSERVED" if days is not None else "UNKNOWN",
            days,
            period,
            f"{source_ref} game_time",
            "Retained economy-day span from simulation start to final cargo delivery.",
            "UNKNOWN when game time was not retained.",
        )
    ]
    for metric in evaluation.get("metrics") or []:
        value = _number(metric.get("actual"))
        planned = _number(metric.get("planned"))
        derivation = metric.get("provenance", "Retained native evaluation metric.")
        if planned is not None and value is not None:
            derivation = (
                f"{derivation} Retained planned estimate: {planned} [{metric.get('unit')}]."
            )
        metrics.append(
            _metric(
                metric["name"],
                metric["unit"],
                "DERIVED"
                if metric["name"] == "revenue_profit_residual"
                else "OBSERVED"
                if value is not None
                else "UNKNOWN",
                value,
                period,
                f"{source_ref} metrics[{metric['name']}]",
                derivation,
                "Retained evaluation actual=None keeps this UNKNOWN; unknown is not zero."
                if value is None
                else "Direct native measurement; nothing invented.",
                metric.get("provenance", ""),
            )
        )
    services: list[ServicePerformance] = []
    for position, service in enumerate(evaluation.get("services") or [], 1):
        rows = []
        for metric in service.get("metrics") or []:
            value = _number(metric.get("actual"))
            rows.append(
                _metric(
                    metric["name"],
                    metric["unit"],
                    "OBSERVED" if value is not None else "UNKNOWN",
                    value,
                    period,
                    f"{source_ref} services[{position}].metrics[{metric['name']}]",
                    metric.get("provenance", "Retained service batch measurement."),
                    "Retained evaluation actual=None keeps this UNKNOWN; unknown is not zero."
                    if value is None
                    else "Direct native measurement bound to the verified service receipt.",
                    metric.get("provenance", ""),
                )
            )
        services.append(
            ServicePerformance(
                scope=service.get("route_id") or f"service-{position}",
                label=f"Service {position}",
                status=service.get("status"),
                metrics=rows,
            )
        )
    bottlenecks = _batch_evidence_bottlenecks(evaluation, source_ref)
    operating_costs = next((m for m in metrics if m.name == "operating_costs"), None)
    finance = dict(
        freight_revenue=_metric_value(metrics, "delivery_revenue"),
        capex=_metric_value(metrics, "total_capex"),
        vehicle_operating_expenses=operating_costs.value if operating_costs else None,
        known_unallocated_expenses=None,
        unknown_cash_movements=None,
    )
    # Batch evidence retains no series, so bottleneck-derived advice is empty by design.
    rows = _finance_recommendations(finance)
    for row in evaluation.get("feedback") or []:
        code = row["code"]
        text = row.get("recommendation", "Retained P07 feedback advisory.")
        rows.append(
            AdvisoryRecommendation(
                recommendation_id="",
                code=code,
                scope=row.get("scope", "network"),
                confidence=(
                    "HYPOTHESIS"
                    if code in {"batch_capacity_utilization", "source_waiting_backlog"}
                    else "DERIVED"
                ),
                reason=text,
                evidence=[row.get("metric", "network metrics"), f"source {source_ref}"],
                expected_improvement_direction=_FEEDBACK_DIRECTION.get(code, text),
                advisory_only=True,
                missing_information=["Existing limitations of the retained evaluation."],
                suggested_next_experiment=(
                    _CAPACITY_EXPERIMENT_TEXT
                    if code in {"batch_capacity_utilization", "source_waiting_backlog"}
                    else text
                ),
            )
        )
    window = dict(
        start_economy_date=economy.get("simulation_start_date"),
        end_economy_date=economy.get("final_cargo_delivery_date"),
        economy_days=days,
        samples=None,
    )
    return PerformanceInsights(
        schema_version=SCHEMA_VERSION,
        classification=str(evaluation.get("classification", "UNKNOWN_CLASSIFICATION")),
        source_kind="network-evaluation",
        source_ref=source_ref,
        source_sha256=source_sha256,
        native_terminal_status=None,
        world_identity=world_identity,
        observation_window=window,
        metrics=metrics,
        services=services,
        time_series={},
        interval_series=[],
        bottlenecks=bottlenecks,
        recommendations=_sorted_recommendations(rows),
        limitations=list(_BASE_LIMITATIONS) + list(evaluation.get("limitations") or []),
        financial_attribution=_financial_attribution_status(evaluation),
    )


def _financial_attribution_status(document: dict) -> dict | None:
    """Compact financial-attribution view of the passed document alone.

    Reads no evidence directories (per-service amounts come from the document
    itself); the deferred import avoids a module import cycle because the
    attribution layer imports this module's helpers inside its pipeline.
    """
    from app.experiments.financial_attribution import compact_status

    return compact_status(document)


def build_performance_insights(
    document: dict,
    *,
    source_kind: str | None = None,
    source_ref: str = "controlled input",
    source_sha256: str | None = None,
    world_identity: dict[str, str] | None = None,
) -> PerformanceInsights:
    """Dispatch on the detected P07 document shape."""
    if source_kind is None:
        if document.get("snapshots"):
            source_kind = "continuous"
        elif document.get("services") or document.get("metrics"):
            source_kind = "network-evaluation"
        else:
            raise ValueError("document is neither a continuous summary nor a network evaluation")
    builder = {
        "continuous": build_continuous_insights,
        "network-evaluation": build_network_insights,
    }.get(source_kind)
    if builder is None:
        raise ValueError(f"unknown source kind: {source_kind}")
    return builder(
        document,
        source_ref=source_ref,
        source_sha256=source_sha256,
        world_identity=world_identity,
    )


# ---------------------------------------------------------------------------
# Comparisons
# ---------------------------------------------------------------------------


def comparison_row(
    insights: PerformanceInsights, *, run_id: str, configuration: str | None = None
) -> dict:
    """Flatten an insights document into a comparable normalized row."""
    # Network-level metrics are preferred; service entries with equal names are skipped.
    cargo_m = _network_metric(insights.metrics, "network_delivered_cargo", "delivered_cargo")
    revenue_m = _network_metric(insights.metrics, "network_revenue", "delivery_revenue")
    capex_m = _network_metric(insights.metrics, "observed_capex", "total_capex")
    cargo = cargo_m.value if cargo_m is not None else None
    revenue = revenue_m.value if revenue_m is not None else None
    capex = capex_m.value if capex_m is not None else None
    days = insights.observation_window.get("economy_days")
    revenue_per_cargo = revenue / cargo if revenue is not None and cargo not in (None, 0) else None
    return dict(
        run_id=run_id,
        source=insights.source_ref,
        source_kind=insights.source_kind,
        classification=insights.classification,
        world_identity=insights.world_identity,
        configuration=configuration,
        observation_days=days,
        cargo_delivered=cargo,
        revenue_gbp=revenue,
        capex_gbp=capex,
        cargo_per_day=_rate(cargo, days),
        revenue_per_day=_rate(revenue, days),
        revenue_per_cargo=revenue_per_cargo,
    )


def _same_world(a: dict[str, str] | None, b: dict[str, str] | None) -> bool:
    if not a or not b:
        return False
    return all(
        a.get(key) is not None and a.get(key) == b.get(key) for key in sorted(set(a) | set(b))
    )


def compare_performance_rows(rows: list[dict]) -> dict:
    """Descriptive comparison; matched worlds are labeled, causality is not claimed."""
    if len(rows) < 2:
        raise ValueError("comparison requires at least two run rows")
    normalized = [
        (
            row,
            bool(row.get("cargo_delivered") is not None and row.get("observation_days")),
        )
        for row in rows
    ]
    # Same-world identification is kept even when one side lacks normalized data.
    world_matches: list[list[str]] = []
    matched_pairs: list[list[str]] = []
    for index, (row, complete) in enumerate(normalized):
        for other_index, (other, other_complete) in enumerate(normalized):
            if other_index <= index:
                continue
            if _same_world(row.get("world_identity"), other.get("world_identity")):
                world_matches.append([row.get("run_id"), other.get("run_id")])
                if complete and other_complete:
                    matched_pairs.append([row.get("run_id"), other.get("run_id")])
    matched_ids = {run_id for pair in matched_pairs for run_id in pair}
    world_matched_ids = {run_id for pair in world_matches for run_id in pair}
    # Same-world runs whose only partners lack comparable data cannot be normalized.
    blocked_ids = world_matched_ids - matched_ids
    results = []
    for row, complete in normalized:
        status = "INSUFFICIENT_DATA"
        if complete:
            if row.get("run_id") in matched_ids:
                status = "MATCHED_DESCRIPTIVE"
            elif row.get("run_id") in blocked_ids:
                status = "INSUFFICIENT_DATA"
            elif row.get("world_identity"):
                status = "UNRELATED_WORLD"
        results.append(ComparisonRow(**row, status=status))
    comparable_ids = {row.get("run_id") for row, complete in normalized if complete}
    comparable_statuses = [row.status for row in results if row.run_id in comparable_ids]
    if matched_pairs and len(comparable_statuses) >= 2:
        classification = "MATCHED_WORLD_COMPARISON"
    elif comparable_statuses and all(status == "UNRELATED_WORLD" for status in comparable_statuses):
        classification = "DESCRIPTIVE_UNRELATED_COMPARISON"
    else:
        classification = "INSUFFICIENT_DATA"
    policy = (
        "Descriptive comparison only. Same-world rows share a retained world recipe; "
        "normalization by economy days does not equalize horizons, serial batch lengths or "
        "cargo mixes. Higher numbers in an unrelated world must never be read as an optimizer "
        "improvement; matched-world rows stay descriptive, never causal."
    )
    return dict(
        schema_version=SCHEMA_VERSION,
        classification=classification,
        policy=policy,
        matched_pairs=matched_pairs,
        matched_worlds=world_matches,
        rows=[row.model_dump(mode="json") for row in results],
    )


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def render_terminal_summary(insights: PerformanceInsights) -> str:
    """Concise offline performance summary; UNKNOWN stays visible."""
    window = insights.observation_window
    days = window.get("economy_days")
    samples = window.get("samples")
    lines = [
        f"P07 PERFORMANCE INSIGHTS - {insights.classification}",
        f"Source: {insights.source_kind} {insights.source_ref}"
        + (f" (sha256 {insights.source_sha256[:12]}...)" if insights.source_sha256 else ""),
    ]
    if insights.native_terminal_status:
        lines.append(f"Native terminal status: {insights.native_terminal_status}")
    lines.append(
        f"Window: economy dates {_fmt(window.get('start_economy_date'))}.."
        f"{_fmt(window.get('end_economy_date'))} ({_fmt(days)} economy days"
        + (f", {samples} samples" if samples is not None else "")
        + ")"
    )
    for label, names, unit in (
        ("delivered cargo", ("network_delivered_cargo", "delivered_cargo"), "cargo_units"),
        ("network revenue", ("network_revenue", "delivery_revenue"), "GBP"),
        ("observed CAPEX", ("observed_capex", "total_capex"), "GBP"),
    ):
        metric = _network_metric(insights.metrics, *names)
        if metric is not None:
            value, status = _fmt(metric.value), metric.status
        elif any(m.name in names and m.status == "UNKNOWN" for m in insights.metrics):
            value, status = "UNKNOWN", "UNKNOWN"
        else:
            value, status = "UNKNOWN", "NOT_DECLARED"
        lines.append(f"{label}: {value} {unit} [{status}]")
    aggregate = next((m for m in insights.metrics if m.name == "observed_aggregate_expenses"), None)
    residual = next((m for m in insights.metrics if m.name == "unattributed_cash_movement"), None)
    lines.append(
        "Observed aggregate expenses: "
        + _fmt(aggregate.value if aggregate else None)
        + " GBP; unattributed cash movement: "
        + _fmt(residual.value if residual else None)
        + " GBP (UNKNOWN is not zero; no profit or ROI is derived while attribution is incomplete)"
    )
    for service in insights.services:
        cargo_day = _metric_value(service.metrics, "cargo_per_economy_day")
        backlog = _metric_value(service.metrics, "sampled_backlog_end_units")
        episodes = _metric_value(service.metrics, "unloading_episodes")
        assessment = next((b for b in insights.bottlenecks if b.scope == service.scope), None)
        suffix = (
            f" [{assessment.classification}]"
            if assessment is not None and assessment.status == "HYPOTHESIS"
            else ""
        )
        lines.append(
            f"  {service.label}: cargo/day {_fmt(cargo_day)}, backlog end "
            f"{_fmt(backlog)} units, episodes {_fmt(episodes)}{suffix}"
        )
    hypotheses = [b for b in insights.bottlenecks if b.status == "HYPOTHESIS"]
    insufficient = [b for b in insights.bottlenecks if b.data_status == "INSUFFICIENT_DATA"]
    lines.append(
        f"Bottlenecks: {len(hypotheses)} hypothesis, {len(insufficient)} insufficient-data "
        f"of {len(insights.bottlenecks)} assessments"
    )
    codes = sorted({row.code for row in insights.recommendations})
    lines.append(
        f"Advisory recommendations: {len(insights.recommendations)} ({', '.join(codes)})"
        if insights.recommendations
        else "Advisory recommendations: 0"
    )
    lines.append("Limitations apply; see performance-report.md. UNKNOWN is not zero.")
    return "\n".join(lines)


def render_insights_markdown(insights: PerformanceInsights) -> str:
    """Human-readable Markdown report mirroring the machine-readable document."""
    window = insights.observation_window
    lines = [
        f"# P07 performance insights - {insights.classification}",
        "",
        f"*Source*: `{insights.source_kind}` `{insights.source_ref}`"
        + (f" · canonical sha256 `{insights.source_sha256}`" if insights.source_sha256 else "")
        + "",
        f"*Observation window*: economy dates {_fmt(window.get('start_economy_date'))}.."
        f"{_fmt(window.get('end_economy_date'))} ({_fmt(window.get('economy_days'))} economy days"
        + (f", {window.get('samples')} samples" if window.get("samples") is not None else "")
        + ")",
    ]
    if insights.world_identity:
        identity = ", ".join(f"{k}={v}" for k, v in insights.world_identity.items())
        lines += [f"*World identity*: {identity}"]
    if insights.native_terminal_status:
        lines += [
            "",
            f"**Native terminal status: {insights.native_terminal_status}.** Offline recovery "
            "provenance is separate and never re-labels the consumed attempt.",
        ]
    lines += [
        "",
        "## Headline metrics",
        "",
        "| Metric | Value | Unit | Status |",
        "|---|---:|---|---|",
    ]
    for metric in insights.metrics:
        lines.append(
            f"| `{metric.name}` | {_fmt(metric.value)} | {metric.unit} | {metric.status} |"
        )
    lines += [
        "",
        "Every value declares unit, window, source, derivation and missing-data behaviour in "
        "`insights.json`; UNKNOWN is not zero.",
        "",
        "## Services",
        "",
        "| Service | Scope | Rank by cargo/day | Cargo window | Cargo/day | Backlog end | "
        "Episodes |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for service in insights.services:
        lines.append(
            f"| {service.label} | `{service.scope[:24]}…` | {_fmt(service.rank_by_cargo_per_day)} "
            f"| {_fmt(_metric_value(service.metrics, 'delivered_cargo'))} "
            f"| {_fmt(_metric_value(service.metrics, 'cargo_per_economy_day'))} "
            f"| {_fmt(_metric_value(service.metrics, 'sampled_backlog_end_units'))} "
            f"| {_fmt(_metric_value(service.metrics, 'unloading_episodes'))} |"
        )
    lines += ["", "## Bottleneck analysis", ""]
    for assessment in insights.bottlenecks:
        lines.append(f"### {assessment.label} ({assessment.classification})")
        observations_text = "; ".join(
            f"{key}={_fmt(value)}" for key, value in assessment.observations.items()
        )
        lines += [
            "",
            f"- status: {assessment.status}; data: {assessment.data_status}",
            f"- reasoning: {assessment.reasoning}",
            f"- evidence: {'; '.join(assessment.evidence)}",
            f"- observations: {observations_text}",
            f"- missing information: {'; '.join(assessment.missing_information)}",
        ]
    lines += ["", "## Recommendations (advisory only)", ""]
    if insights.recommendations:
        for row in insights.recommendations:
            lines += [
                f"### {row.recommendation_id} `{row.code}` - {row.scope} [{row.confidence}]",
                "",
                f"- reason: {row.reason}",
                f"- expected improvement direction: {row.expected_improvement_direction}",
                f"- evidence: {'; '.join(row.evidence)}",
                f"- missing information: {'; '.join(row.missing_information)}",
                f"- suggested next experiment: {row.suggested_next_experiment}",
                f"- advisory only: {row.advisory_only}",
            ]
    else:
        lines.append("No recommendation was supportable from retained evidence.")
    if insights.comparisons is not None:
        comparison = insights.comparisons
        lines += [
            "",
            f"## Run comparison ({comparison['classification']})",
            "",
            comparison["policy"],
            "",
            "| Run | Days | Cargo | Revenue GBP | Cargo/day | Revenue/day | World | Status |",
            "|---|---:|---:|---:|---:|---:|---|---|",
        ]
        for row in comparison["rows"]:
            world = (
                ",".join(f"{k}={v}" for k, v in row["world_identity"].items())
                if row["world_identity"]
                else "UNKNOWN"
            )
            lines.append(
                f"| {row['run_id'][:20]}… | {_fmt(row['observation_days'])} "
                f"| {_fmt(row['cargo_delivered'])} | {_fmt(row['revenue_gbp'])} "
                f"| {_fmt(row['cargo_per_day'])} | {_fmt(row['revenue_per_day'])} "
                f"| {world} | {row['status']} |"
            )
    lines += ["", "## Limitations", ""]
    lines += [f"- {text}" for text in insights.limitations]
    lines += [
        "",
        "Generated offline from existing P07 artifacts; no native launch, connection or claim.",
    ]
    return "\n".join(lines) + "\n"


def render_insights_charts(insights: PerformanceInsights) -> str:
    """Operational charts reusing the existing P07 SVG bar generator."""
    charts = []

    def network_value(*names) -> int | float | None:
        metric = _network_metric(insights.metrics, *names)
        return metric.value if metric is not None else None

    delivery_rows = [
        (service.label, _metric_value(service.metrics, "delivered_cargo"), "#176b86")
        for service in insights.services
    ]
    delivery_rows.append(
        (
            "Network",
            network_value("network_delivered_cargo", "delivered_cargo"),
            "#176b86",
        )
    )
    charts.append(_bars("Delivered cargo over the window", delivery_rows, "cargo units"))
    rate_rows = [
        (
            service.label,
            _metric_value(service.metrics, "cargo_per_economy_day"),
            "#176b86",
        )
        for service in insights.services
    ]
    rate_rows.append(
        (
            "Network",
            network_value("network_cargo_per_economy_day", "cargo_per_economy_day"),
            "#176b86",
        )
    )
    charts.append(_bars("Cargo per economy day by scope", rate_rows, "cargo units/day"))
    backlog_rows = []
    for service in insights.services:
        backlog_rows.append(
            (
                f"{service.label} end",
                _metric_value(service.metrics, "sampled_backlog_end_units"),
                "#176b86",
            )
        )
        backlog_rows.append(
            (
                f"{service.label} max",
                _metric_value(service.metrics, "sampled_backlog_max_units"),
                "#b66a08",
            )
        )
    if backlog_rows:
        charts.append(
            _bars("Sampled station backlog (end vs maximum)", backlog_rows, "cargo units")
        )
    charts.append(
        _bars(
            "Revenue over time (retained interval samples)",
            [
                (f"{row.period} {row.index}", row.revenue, "#176b86")
                for row in insights.interval_series
                if row.period == "monthly"
            ],
            "GBP",
        )
    )
    charts.append(
        _bars(
            "Delivered cargo over time (annual economy-year windows)",
            [
                (f"Year {row.index}", row.delivered_cargo, "#176b86")
                for row in insights.interval_series
                if row.period == "annual"
            ],
            "cargo units",
        )
    )
    finance_rows = [
        ("Window revenue", network_value("network_revenue", "delivery_revenue"), "#176b86")
    ]
    capex = _metric_value(insights.metrics, "observed_capex", "total_capex")
    if capex is not None:
        finance_rows.append(("Observed CAPEX", capex, "#b66a08"))
    aggregate = next((m for m in insights.metrics if m.name == "observed_aggregate_expenses"), None)
    finance_rows.append(
        ("Observed aggregate expenses", aggregate.value if aggregate else None, "#b66a08")
    )
    charts.append(_bars("Revenue vs retained spending (no profit claim)", finance_rows, "GBP"))
    for scope in sorted(insights.time_series):
        points = insights.time_series[scope]
        if not points:
            continue
        charts.append(
            _bars(
                f"Delivered cargo over time - {scope[:24]}…",
                [(str(point.economy_date), point.delivered, "#176b86") for point in points],
                "cargo units",
            )
        )
        charts.append(
            _bars(
                f"Sampled station backlog over time - {scope[:24]}…",
                [(str(point.economy_date), point.waiting, "#176b86") for point in points],
                "cargo units",
            )
        )
    recommendation_counts = Counter(row.code for row in insights.recommendations)
    if recommendation_counts:
        charts.append(
            _bars(
                "Advisory recommendations by code",
                sorted((code, count, "#176b86") for code, count in recommendation_counts.items()),
                "recommendations",
            )
        )
    body = (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        "<title>P07 performance insights</title>"
        "<style>body{font:16px system-ui;max-width:1050px;margin:auto;padding:24px}"
        "svg{width:100%}small,.axis{fill:#667}.unknown{fill:#955}</style>"
        f"<h1>P07 performance insights - {insights.classification}</h1>"
        f"<p>{ADVISORY_NOTE}</p><p>UNKNOWN is never zero. Retained evidence source: "
        f"{insights.source_kind} {insights.source_ref}.</p>"
    )
    if insights.native_terminal_status:
        body += (
            f"<p><strong>Native terminal status: {insights.native_terminal_status}. "
            "Offline recovery is derived separately.</strong></p>"
        )
    return body + "".join(charts) + "</html>"


# ---------------------------------------------------------------------------
# Pipeline over retained report directories
# ---------------------------------------------------------------------------


def _load_report(source: Path) -> tuple[dict, str, str, str]:
    """Read a P07 report directory without modifying it."""
    summary_path = source / "summary.json"
    evaluation_path = source / "evaluation.json"
    if summary_path.is_file():
        name, kind = "summary.json", "continuous"
    elif evaluation_path.is_file():
        name, kind = "evaluation.json", "network-evaluation"
    else:
        raise ValueError(
            f"{source} contains neither a P07 continuous summary.json nor an evaluation.json"
        )
    raw = (source / name).read_bytes()
    document = json.loads(raw)
    return document, kind, f"{source / name}", hashlib.sha256(raw).hexdigest()


def _world_identity(source: Path, document: dict) -> dict[str, str] | None:
    """Best-effort world identity from retained PRELAUNCH records (read-only)."""
    candidates = [source / "PRELAUNCH.json"]
    recovery = (document.get("offline_recovery") or {}).get("original_directory")
    if recovery:
        recovery_path = Path(recovery)
        if not recovery_path.is_absolute():
            recovery_path = source / recovery_path
        candidates.append(recovery_path / "PRELAUNCH.json")
    evidence_directory = document.get("evidence_directory")
    if evidence_directory:
        candidates.append(Path(evidence_directory) / "PRELAUNCH.json")
    for candidate in candidates:
        try:
            payload = json.loads(candidate.read_bytes())
        except OSError, json.JSONDecodeError:
            continue
        world = payload.get("world") if isinstance(payload, dict) else None
        if isinstance(world, dict) and world:
            return {str(key): str(value) for key, value in sorted(world.items())}
    return None


def analyze_performance(source: Path, output: Path, *, compare: tuple[Path, ...] = ()) -> dict:
    """Build one insights document (plus optional comparison) into the output.

    Retained evidence directories are read-only and never written to. The guard
    covers both the passed source roots and evidence directories referenced
    inside the retained documents themselves.
    """
    report_sources = tuple(report.resolve() for report in (source, *compare))
    loaded = []
    referenced_roots: list[Path] = []
    for report_source in report_sources:
        document, kind, document_ref, digest = _load_report(report_source)
        loaded.append((report_source, document, kind, document_ref, digest))
        for referenced in (
            (document.get("offline_recovery") or {}).get("original_directory"),
            document.get("evidence_directory"),
        ):
            if referenced:
                candidate = Path(referenced)
                candidate = candidate if candidate.is_absolute() else report_source / candidate
                referenced_roots.append(candidate)
    destinations = [output.resolve(), *(output.resolve() / name for name in OUTPUT_NAMES)]
    try:
        roots = [root.resolve() for root in (*report_sources, *referenced_roots)]
    except OSError:
        roots = list(report_sources)
    if any(target.is_relative_to(root) for root in roots for target in destinations):
        raise ValueError("insights output must not modify retained evidence")
    primary = None
    rows = []
    for report_source, document, kind, document_ref, digest in loaded:
        insights = build_performance_insights(
            document,
            source_kind=kind,
            source_ref=document_ref,
            source_sha256=digest,
            world_identity=_world_identity(report_source, document),
        )
        if primary is None:
            primary = insights
        rows.append(comparison_row(insights, run_id=report_source.name))
    comparison = compare_performance_rows(rows) if len(rows) > 1 else None
    document = primary.model_copy(update={"comparisons": comparison}) if comparison else primary
    output.mkdir(parents=True, exist_ok=True)
    (output / "insights.json").write_text(document.model_dump_json(indent=2) + "\n")
    (output / "performance-report.md").write_text(render_insights_markdown(document))
    (output / "terminal-summary.txt").write_text(render_terminal_summary(document) + "\n")
    (output / "insights-charts.html").write_text(render_insights_charts(document))
    stale_comparison = output / "comparison.json"
    if comparison is not None:
        (output / "comparison.json").write_text(json.dumps(comparison, indent=2) + "\n")
    elif stale_comparison.exists():
        stale_comparison.unlink()
    return dict(
        output=str(output),
        classification=document.classification,
        metrics=len(document.metrics),
        services=len(document.services),
        bottlenecks=len(document.bottlenecks),
        recommendations=len(document.recommendations),
        insights=str(output / "insights.json"),
        performance_report=str(output / "performance-report.md"),
        terminal_summary=str(output / "terminal-summary.txt"),
        charts=str(output / "insights-charts.html"),
        comparison=str(output / "comparison.json") if comparison is not None else None,
    )
