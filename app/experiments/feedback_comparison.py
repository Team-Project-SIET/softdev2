"""Offline P07 reporting for a matched Baseline versus Feedback-aware experiment."""

import json
from decimal import Decimal
from html import escape
from pathlib import Path

from app.experiments.freight_analytics import _bars
from app.experiments.freight_evaluation import FreightMetric
from app.experiments.freight_network import evaluate_freight_network
from app.planning.domain import ExecutionPlan, PlanningScenario

LIMITATIONS = (
    "One matched pair is descriptive evidence, not a general improvement or causal estimate.",
    "Lower estimated objective alone does not establish better actual performance.",
    "Serial first-paid-batch observations do not measure concurrent network throughput.",
    "OPEX, net return and ROI remain unknown without direct supporting evidence.",
    "Identical selected plans require no native launches; actual comparison then remains unknown.",
)


def write_comparison(
    output: Path,
    planning_manifest: dict,
    baseline_plan: ExecutionPlan,
    baseline_scenario: PlanningScenario,
    feedback_plan: ExecutionPlan,
    feedback_scenario: PlanningScenario,
    native_directories: dict[str, Path] | None = None,
) -> dict:
    """Validate selected plans; orchestration supplies independently verified provenance."""
    if native_directories:
        raise ValueError(
            "matched native receipt ingestion requires verified clone provenance; unsupported"
        )
    if output.is_symlink() or any(parent.is_symlink() for parent in output.parents):
        raise ValueError("comparison output must not use symlinks")
    if any(
        (output / name).exists() or (output / name).is_symlink()
        for name in ("comparison.json", "charts.html")
    ):
        raise ValueError("comparison output already exists")
    protected = planning_manifest.get("protected_directories", [])
    for directory in protected:
        path = Path(directory).resolve()
        if output.resolve() == path or path in output.resolve().parents:
            raise ValueError("comparison output is inside protected evidence")
    variants = {}
    metrics_by_variant: dict[str, tuple[FreightMetric, ...]] = {}
    for label, plan, scenario in (
        ("baseline", baseline_plan, baseline_scenario),
        ("feedback", feedback_plan, feedback_scenario),
    ):
        network = evaluate_freight_network(plan, scenario)
        metrics_by_variant[label] = network.metrics
        variants[label] = dict(
            selected_plan_digest=network.plan_digest,
            status="not-executed",
            metrics=[m.model_dump(mode="json") for m in network.metrics],
            services=[s.model_dump(mode="json") for s in network.services],
            evidence=None,
            roi=None,
        )
    # Unknown is preserved; neither missing evidence nor failure is a numeric zero.
    delta = {}
    baseline = {m.name: m for m in metrics_by_variant["baseline"]}
    for metric in metrics_by_variant["feedback"]:
        other = baseline[metric.name]
        delta[metric.name] = {
            "planned": _difference(metric.planned, other.planned),
            "actual": _difference(metric.actual, other.actual),
        }
    report = dict(
        schema_version=1,
        classification="MATCHED_FEEDBACK_COMPARISON",
        provenance=planning_manifest,
        variants=variants,
        historical_reference=planning_manifest.get("historical_reference"),
        feedback_minus_baseline=delta,
        limitations=LIMITATIONS,
    )
    output.mkdir(parents=True, exist_ok=True)
    (output / "comparison.json").write_text(json.dumps(report, indent=2) + "\n")
    (output / "charts.html").write_text(render_html(report))
    return report


def _difference(feedback: Decimal | None, baseline: Decimal | None) -> str | None:
    return str(feedback - baseline) if feedback is not None and baseline is not None else None


def render_html(report: dict) -> str:
    charts = []
    for name, title, unit in (
        ("delivered_cargo", "Delivered cargo", "cargo units"),
        ("delivery_revenue", "Delivery revenue", "GBP"),
        ("total_capex", "Total CAPEX", "GBP"),
        ("vehicle_profit", "Vehicle profit", "GBP"),
        ("operating_costs", "OPEX", "GBP"),
        ("net_return", "Net return", "GBP"),
    ):
        rows = []
        for label, variant in report["variants"].items():
            metric = next(m for m in variant["metrics"] if m["name"] == name)
            rows.extend(
                (f"{label} {key}", metric[key], color)
                for key, color in (("planned", "#b66a08"), ("actual", "#176b86"))
            )
        charts.append(_bars(title, rows, unit))
    utilization = []
    for label, variant in report["variants"].items():
        for index, service in enumerate(variant["services"], 1):
            for name in ("load_fill", "capacity_utilization", "time_utilization"):
                metric = next((m for m in service["metrics"] if m["name"] == name), None)
                value = metric["actual"] if metric else None
                utilization.append((f"{label} S{index} {name}", value, "#176b86"))
    charts.append(_bars("Measured service utilization", utilization, "ratio"))
    errors = []
    for label, variant in report["variants"].items():
        for metric in variant["metrics"]:
            if metric["name"] in ("total_capex", "infrastructure_capex", "vehicle_purchase"):
                errors.append((f"{label} {metric['name']}", metric["difference"], "#176b86"))
    charts.append(_bars("Estimation error: actual minus planned", errors, "GBP"))
    charts.append(
        _bars(
            "ROI",
            [(label, variant["roi"], "#176b86") for label, variant in report["variants"].items()],
            "ratio",
        )
    )
    reference = report.get("historical_reference")
    if reference:
        reference_rows = [
            (m["name"], m["actual"], "#667788")
            for m in reference.get("metrics", [])
            if m.get("unit") == "GBP"
        ]
        charts.append(
            "<p>Historical reference only; these actuals belong to neither experiment variant.</p>"
        )
        charts.append(_bars("Historical reference economics", reference_rows, "GBP"))
    limitations = "".join(f"<li>{escape(item)}</li>" for item in report["limitations"])
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        "<title>Matched feedback comparison</title><style>"
        "body{font:16px system-ui;max-width:1000px;margin:2rem auto;padding:1rem}"
        "svg{width:100%;background:#f5f7fa}text{font-size:13px}.unknown{fill:#666}"
        "</style><h1>Baseline versus Feedback-aware P05</h1>"
        "<p>Unknown actuals remain unknown. Estimated objectives are not performance evidence.</p>"
        + "".join(charts)
        + f"<h2>Limitations</h2><ul>{limitations}</ul><h2>Provenance</h2><pre>"
        + escape(json.dumps(report["provenance"], indent=2))
        + "</pre></html>"
    )
