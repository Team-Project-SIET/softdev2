"""Offline CSV/JSON and self-contained HTML charts for native freight history."""

import csv
import json
from html import escape
from pathlib import Path
from statistics import mean, median, stdev

from app.experiments.comparison import MetricSummary
from app.experiments.freight_evaluation import FreightEvaluation, evaluate_freight
from app.experiments.freight_history import FreightHistory


def summarize(runs: tuple[FreightEvaluation, ...]) -> dict:
    groups: dict[str, list[FreightEvaluation]] = {}
    for run in runs:
        if run.status == "verified-delivery":
            assert run.cohort_digest is not None
            groups.setdefault(run.cohort_digest, []).append(run)
    cohorts = []
    for digest, members in groups.items():
        metrics: dict[str, MetricSummary] = {}
        for name in dict.fromkeys(metric.name for run in members for metric in run.metrics):
            numbers = [
                float(metric.actual)
                for run in members
                for metric in run.metrics
                if metric.name == name and metric.actual is not None
            ]
            if numbers:
                metrics[name] = MetricSummary(
                    count=len(numbers),
                    mean=mean(numbers),
                    median=median(numbers),
                    minimum=min(numbers),
                    maximum=max(numbers),
                    standard_deviation=stdev(numbers) if len(numbers) > 1 else 0,
                )
        cohorts.append(
            dict(
                cohort_digest=digest,
                definition=members[0].cohort_definition,
                runs=[run.run_name for run in members],
                count=len(members),
                trend_available=len(members) > 1,
                metrics={name: value.model_dump() for name, value in metrics.items()},
            )
        )
    return dict(
        schema_version=1,
        runs=[run.model_dump(mode="json") for run in runs],
        cohorts=cohorts,
        successful_deliveries=sum(run.status == "verified-delivery" for run in runs),
        failed_attempts=sum(run.status == "failed" for run in runs),
        comparison_policy="No pooled averages across cohorts. Failed attempts have unknown "
        "delivery metrics and are excluded from successful-delivery averages.",
    )


def _value(run, name):
    return next((m for m in run.metrics if m.name == name), None)


def _bars(title, rows, unit, maximum=None):
    """A zero-based horizontal chart; unknown values retain a visible row."""
    known = [abs(float(value)) for _, value, _ in rows if value is not None]
    scale = maximum or max(known, default=1) or 1
    height = 48 + 38 * len(rows)
    out = [
        f'<svg role="img" aria-label="{escape(title)}" viewBox="0 0 800 {height}">',
        f"<title>{escape(title)}</title>",
        '<text x="280" y="20" class="axis">0</text>',
        f'<text x="780" y="20" text-anchor="end" class="axis">{scale:g} {escape(unit)}</text>',
    ]
    for i, (label, value, color) in enumerate(rows):
        y = 32 + i * 38
        out.append(f'<text x="10" y="{y + 19}">{escape(label)}</text>')
        if value is None:
            out.append(f'<text x="290" y="{y + 19}" class="unknown">unknown</text>')
        else:
            width = abs(float(value)) / scale * 390
            out.append(f'<rect x="280" y="{y}" width="{width:.2f}" height="25" fill="{color}"/>')
            out.append(f'<text x="{290 + width:.2f}" y="{y + 18}">{float(value):g}</text>')
    out.append("</svg>")
    return f"<h3>{escape(title)} <small>{escape(unit)}</small></h3>" + "".join(out)


def render_html(runs: tuple[FreightEvaluation, ...], summary: dict) -> str:
    charts = []
    for name, label, unit in (
        ("delivered_cargo", "Planned batch vs actual delivery", "cargo units"),
        ("total_capex", "Planned vs actual CAPEX", "GBP"),
        ("vehicles", "Planned vs actual vehicles", "vehicles"),
    ):
        rows = []
        for run in runs:
            metric = _value(run, name)
            prefix = f"A{run.attempt} {run.mode}"
            rows.extend(
                [
                    (prefix + " planned", metric.planned if metric else None, "#b66a08"),
                    (prefix + " actual", metric.actual if metric else None, "#176b86"),
                ]
            )
        charts.append(_bars(label, rows, unit))
    performance = "".join(charts)
    finance = []
    for run in runs:
        for name, label in (
            ("infrastructure_capex", "infrastructure CAPEX"),
            ("vehicle_purchase", "purchase"),
            ("delivery_revenue", "revenue"),
            ("vehicle_profit", "vehicle profit"),
            ("operating_costs", "full operating costs"),
            ("net_return", "net return"),
        ):
            metric = _value(run, name)
            finance.append(
                (
                    f"A{run.attempt} {label}",
                    metric.actual if metric else None,
                    "#176b86" if name in ("delivery_revenue", "vehicle_profit") else "#b66a08",
                )
            )
    cargo, utilization = [], []
    for run in runs:
        m = _value(run, "delivered_cargo")
        cargo.append((f"A{run.attempt} {run.mode}", m.actual if m else None, "#176b86"))
        for name, label in (
            ("load_fill", "measured load fill"),
            ("time_utilization", "time utilization"),
        ):
            m = _value(run, name)
            utilization.append((f"A{run.attempt} {label}", m.actual if m else None, "#176b86"))
    trends = []
    for cohort in summary["cohorts"]:
        members = [run for run in runs if run.run_name in cohort["runs"]]
        suffix = cohort["cohort_digest"][:8]
        points = []
        for i, run in enumerate(members):
            m = _value(run, "delivery_revenue")
            assert m is not None and m.actual is not None
            points.append((60 + i * 600 / max(1, len(members) - 1), float(m.actual), run.attempt))
        maximum = max(v for _, v, _ in points) * 1.2 or 1
        plot = [
            f'<svg role="img" aria-label="Revenue trend, cohort {suffix}" viewBox="0 0 800 220">',
            "<title>Revenue per paid batch within a comparable cohort</title>",
            '<path d="M60 25 V180 H700" fill="none" stroke="#667"/>',
            '<text x="10" y="20">GBP</text><text x="60" y="210">Attempt</text>',
        ]
        if len(points) > 1:
            coords = " ".join(f"{x:.1f},{180 - v / maximum * 145:.1f}" for x, v, _ in points)
            plot.append(f'<polyline points="{coords}" fill="none" stroke="#176b86"/>')
        for x, v, attempt in points:
            y = 180 - v / maximum * 145
            plot.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="#176b86"/>'
                f'<text x="{x + 12:.1f}" y="{y:.1f}">£{v:g}</text>'
                f'<text x="{x:.1f}" y="198">{attempt}</text>'
            )
        plot.append("</svg>")
        caption = (
            "Comparable descriptive history; no causal claim."
            if len(points) > 1
            else "One comparable run; no trend can be inferred."
        )
        trends.append(
            f"<h3>{escape(members[0].mode)} · cohort {suffix}</h3><p>{caption}</p>" + "".join(plot)
        )
    details = []
    for run in runs:
        rows = []
        for metric in run.metrics:
            actual = str(metric.actual) if metric.actual is not None else "unknown"
            planned = str(metric.planned) if metric.planned is not None else "unknown"
            rows.append(
                "<tr>"
                + "".join(
                    f"<td>{escape(str(v))}</td>"
                    for v in (
                        metric.name,
                        planned,
                        actual,
                        metric.unit,
                        metric.scope,
                        metric.provenance,
                    )
                )
                + "</tr>"
            )
        findings = "".join(f"<li>{escape(text)}</li>" for text in run.findings + run.limitations)
        details.append(
            f"<details><summary>Attempt {run.attempt} · {run.mode} · {run.status}</summary>"
            f"<p>{escape(run.reason or 'Native receipt replay PASS')}</p>"
            f"<p>Source digest: <code>{run.history_key}</code></p><ul>{findings}</ul>"
            '<div class="table"><table><thead><tr><th>Metric</th><th>Planned</th>'
            "<th>Actual</th><th>Unit</th><th>Scope</th><th>Evidence</th></tr></thead>"
            "<tbody>" + "".join(rows) + "</tbody></table></div></details>"
        )
    return (
        """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>P07 freight analytics</title>
<style>body{font:16px system-ui;background:#eef2f5;color:#172532;margin:0}main{max-width:1050px;
margin:auto;padding:28px}section,details{background:white;padding:22px;
margin:20px 0;border-radius:10px}
h1{margin-bottom:8px}h3{font-size:18px}small,.unknown{color:#687580}svg{width:100%;display:block}
svg text{font:14px system-ui;fill:#172532}.axis{fill:#667}
table{border-collapse:collapse;font-size:13px}
td,th{text-align:left;border-bottom:1px solid #ddd;padding:9px}.table{overflow:auto}
summary{cursor:pointer;font-weight:600}code{overflow-wrap:anywhere}li{margin:8px 0}</style><main>
<h1>P07 native freight analytics</h1>
<p>Verified retained evidence. No OpenTTD launch or connection.</p>"""
        + f"""
<p>{summary["successful_deliveries"]} verified deliveries ·
{summary["failed_attempts"]} failed attempts ·
{len(summary["cohorts"])} comparison cohorts</p>
<p>Unknown is not zero. Orange shows planned values or spending; blue shows actual performance.
Company revenue and vehicle profit overlap and must not be added.
Full operating costs and net return
remain unknown. Attempts 4 and 9 are separate service modes and geometries.</p>
<section><h2>1. Planned vs actual performance</h2>{performance}</section>
<section><h2>2. Revenue and spending</h2>{_bars("Financial readbacks", finance, "GBP")}</section>
<section><h2>3. Delivered cargo</h2>{_bars("First paid batch", cargo, "cargo units")}</section>
<section><h2>4. Vehicle utilization</h2>
<p>Load fill is measured at source. Moving/idle time is unavailable.</p>
{_bars("Capacity and time", utilization, "percent", 100)}</section>
<section><h2>5. Performance trends across comparable runs</h2>{"".join(trends)}</section>
<h2>Evidence, findings and limitations</h2>{"".join(details)}</main></html>"""
    )


def analyze(paths: list[Path], history_path: Path, output: Path) -> dict:
    # Keep generated files outside all input evidence packages, including nested aliases.
    roots = [p.resolve() for p in paths]
    destinations = [
        history_path,
        output,
        *(output / name for name in ("summary.json", "metrics.csv", "charts.html")),
    ]
    if any(target.resolve().is_relative_to(p) for p in roots for target in destinations):
        raise ValueError("analysis output/history must not modify retained evidence")
    evaluations = [evaluate_freight(path) for path in paths]
    history = FreightHistory(history_path)
    try:
        history.add(evaluations)
        runs = history.runs()
    finally:
        history.close()
    if any(
        target.resolve().is_relative_to(Path(run.source_directory))
        for run in runs
        for target in destinations
    ):
        raise ValueError("analysis output/history must not modify retained evidence")
    output.mkdir(parents=True, exist_ok=True)
    summary = summarize(runs)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    with (output / "metrics.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            (
                "run",
                "mode",
                "status",
                "source_digest",
                "metric",
                "planned",
                "actual",
                "unit",
                "scope",
                "comparison",
                "difference",
                "provenance",
            )
        )
        for run in runs:
            for m in run.metrics:
                writer.writerow(
                    (
                        run.run_name,
                        run.mode,
                        run.status,
                        run.history_key,
                        m.name,
                        m.planned,
                        m.actual,
                        m.unit,
                        m.scope,
                        m.comparison,
                        m.difference,
                        m.provenance,
                    )
                )
            if not run.metrics:
                writer.writerow(
                    (
                        run.run_name,
                        run.mode,
                        run.status,
                        run.history_key,
                        "delivery_unknown",
                        None,
                        None,
                        "cargo_units",
                        "incomplete",
                        "unavailable",
                        None,
                        run.reason,
                    )
                )
    (output / "charts.html").write_text(render_html(runs, summary))
    return dict(
        successful_deliveries=summary["successful_deliveries"],
        failed_attempts=summary["failed_attempts"],
        cohorts=len(summary["cohorts"]),
        summary=str(output / "summary.json"),
        csv=str(output / "metrics.csv"),
        charts=str(output / "charts.html"),
        history=str(history_path),
    )
