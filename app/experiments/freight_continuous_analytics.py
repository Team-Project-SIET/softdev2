"""Offline P07 reporting over replay-verified continuous freight observations."""

import csv
import hashlib
import json
from html import escape
from pathlib import Path

from app.experiments.freight_analytics import _bars


def _delta(current, previous):
    return None if current is None or previous is None else current - previous


def _complete_sum(values):
    return sum(values) if values and all(v is not None for v in values) else None


def _services(snapshot):
    return {str(service["route_id"]): service for service in snapshot["services"]}


def _metric(snapshot, scope, name):
    if name == "capacity_utilization" and "vehicle_telemetry" in snapshot:
        # Derived ratio of asynchronous point samples, not time-weighted utilization.
        samples = snapshot["vehicle_telemetry"]
        if scope != "network":
            service = _services(snapshot)[scope]
            service_index = service.get("service")
            if service_index is None:
                original = next((s for s in samples if s["vehicle"] == service["vehicle"]), None)
                service_index = original["service"] if original is not None else None
            samples = [s for s in samples if s["service"] == service_index]
        load = _complete_sum([sample.get("load") for sample in samples])
        capacity = _complete_sum([sample.get("capacity") for sample in samples])
        return load / capacity if load is not None and capacity else None
    if scope == "network":
        if name == "capacity_utilization":
            load = _complete_sum([service.get("cargo_load") for service in snapshot["services"]])
            capacity = _complete_sum([service.get("capacity") for service in snapshot["services"]])
            return load / capacity if load is not None and capacity else None
        measured = snapshot["finance"].get(name)
        if measured is not None:
            return measured
        return _complete_sum([service.get(name) for service in snapshot["services"]])
    return _services(snapshot)[scope].get(name)


def _observations(snapshots):
    from app.simulation.openttd.freight_finance import reconcile_snapshots

    revenue, cargo, aggregate_expenses = 0, 0, 0
    observations = []
    for index, snapshot in enumerate(snapshots):
        if index:
            interval = reconcile_snapshots(snapshots[index - 1 : index + 1])
            revenue += interval["freight_revenue"]
            cargo += interval["delivered_cargo"]
            aggregate_expenses += interval["known_unallocated_expenses"]
        observations.append(
            dict(
                snapshot,
                finance=dict(
                    snapshot["finance"],
                    revenue=revenue,
                    delivered_cargo=cargo,
                    known_unallocated_expenses=aggregate_expenses,
                    loan=snapshot["finance"]["loan_balance"],
                ),
                services=[
                    dict(
                        service,
                        delivered_cargo=service.get("delivered"),
                        vehicle_operating_expenses=service.get("operating_costs"),
                        station_waiting=service.get("station_waiting_cargo"),
                    )
                    for service in snapshot["services"]
                ],
            )
        )
    return observations


def _setup_cash_coverage(source, opening, capex):
    """Keep funding-to-baseline movements outside the operating observation window."""
    funding_path = source / "scenario-capital.json"
    if not funding_path.is_file() or capex is None:
        return None
    funding = json.loads(funding_path.read_text())
    finance = opening["finance"]
    if not funding.get("independently_verified"):
        raise ValueError("scenario funding lacks independent verification")
    setup_decrease = funding["balance_after"] - capex - finance["cash"]
    setup_expenses = None
    if (
        funding.get("expenses_after") == 0
        and funding.get("income_after") == 0
        and finance["previous_quarter_expenses"] == 0
        and finance["previous_quarter_income"] == 0
        and finance["quarter_income"] == 0
        and finance["loan_balance"] == funding.get("loan_after")
    ):
        setup_expenses = -finance["quarter_expenses"]
    begin_path = source / "continuous-begin-response.json"
    return dict(
        funding_cash=funding["balance_after"],
        construction_capex=capex,
        operation_opening_cash=finance["cash"],
        setup_cash_decrease_excluding_capex=setup_decrease,
        opening_quarter_expenses_signed=finance["quarter_expenses"],
        opening_quarter_income=finance["quarter_income"],
        setup_expense_categories=None,
        measured_setup_aggregate_expenses=setup_expenses,
        unattributed_setup_cash_decrease=(
            setup_decrease - setup_expenses if setup_expenses is not None else None
        ),
        explanation="Funding and construction precede the operation-start boundary. "
        "This setup cash decrease is excluded from five-year operating deltas; "
        "opening quarter counters are context, not attributed additional costs.",
        evidence=[
            dict(
                reference=str(funding_path),
                sha256=hashlib.sha256(funding_path.read_bytes()).hexdigest(),
            ),
            dict(
                reference=str(begin_path),
                sha256=hashlib.sha256(begin_path.read_bytes()).hexdigest()
                if begin_path.is_file()
                else None,
            ),
        ],
    )


def summarize_continuous(verified: dict, source: Path) -> dict:
    """Derive sampled intervals without substituting missing costs or attribution."""
    from app.simulation.openttd.freight_finance import reconcile_snapshots

    raw_snapshots = verified["snapshots"]
    if not raw_snapshots:
        raise ValueError("continuous evidence has no opening snapshot")
    snapshots = _observations(raw_snapshots)
    by_sequence = {s["sequence"]: s for s in snapshots}
    opening, final = snapshots[0], snapshots[-1]
    scopes = [*_services(opening), "network"]
    evidence = {
        str(snapshot["sequence"]): {
            "reference": str(source / "continuous-snapshots.jsonl"),
            "sequence": snapshot["sequence"],
            "sha256": hashlib.sha256(
                json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "source_digests": snapshot.get("source_digests", []),
        }
        for snapshot in raw_snapshots
    }
    rows = []
    for period, endpoints in (
        ("monthly", verified["monthly"]),
        ("quarterly", verified["quarterly"]),
        ("annual", verified["annual"]),
    ):
        previous = opening
        for index, endpoint in enumerate(endpoints, 1):
            endpoint = by_sequence[endpoint["sequence"]]
            days = endpoint["economy_date"] - previous["economy_date"]
            for scope in scopes:
                revenue = _delta(
                    _metric(endpoint, scope, "revenue"), _metric(previous, scope, "revenue")
                )
                cargo = _delta(
                    _metric(endpoint, scope, "delivered_cargo"),
                    _metric(previous, scope, "delivered_cargo"),
                )
                rows.append(
                    dict(
                        period=period,
                        index=index,
                        scope=scope,
                        start_economy_date=previous["economy_date"],
                        end_economy_date=endpoint["economy_date"],
                        elapsed_economy_days=days,
                        revenue=revenue,
                        delivered_cargo=cargo,
                        revenue_per_economy_day=revenue / days
                        if revenue is not None and days
                        else None,
                        cargo_per_economy_day=cargo / days if cargo is not None and days else None,
                        vehicle_operating_expenses=_delta(
                            _metric(endpoint, scope, "vehicle_operating_expenses"),
                            _metric(previous, scope, "vehicle_operating_expenses"),
                        ),
                        known_unallocated_expenses=_delta(
                            _metric(endpoint, scope, "known_unallocated_expenses"),
                            _metric(previous, scope, "known_unallocated_expenses"),
                        ),
                        completed_delivery_cycles=_delta(
                            _metric(endpoint, scope, "completed_delivery_cycles"),
                            _metric(previous, scope, "completed_delivery_cycles"),
                        ),
                        evidence_refs=[str(previous["sequence"]), str(endpoint["sequence"])],
                    )
                )
            previous = endpoint
    elapsed = final["economy_date"] - opening["economy_date"]
    totals = []
    for scope in scopes:
        revenue = _delta(_metric(final, scope, "revenue"), _metric(opening, scope, "revenue"))
        cargo = _delta(
            _metric(final, scope, "delivered_cargo"), _metric(opening, scope, "delivered_cargo")
        )
        totals.append(
            dict(
                scope=scope,
                revenue=revenue,
                delivered_cargo=cargo,
                revenue_per_economy_day=revenue / elapsed
                if revenue is not None and elapsed
                else None,
                cargo_per_economy_day=cargo / elapsed if cargo is not None and elapsed else None,
                evidence_refs=[str(opening["sequence"]), str(final["sequence"])],
            )
        )
    lifecycle: dict = verified.get("summary") or dict(
        classification="PARTIAL_CONTINUOUS_OBSERVATIONS",
        complete_economy_years=len(verified["annual"]),
    )
    finance: dict = lifecycle.get("financial_metrics") or reconcile_snapshots(raw_snapshots)
    capex = lifecycle.get(
        "infrastructure_and_vehicle_capex_gbp", verified.get("infrastructure_and_vehicle_capex_gbp")
    )
    report: dict = dict(
        schema_version=1,
        classification=(
            "REPLAY_VERIFIED_CONTINUOUS_OBSERVATIONS"
            if verified.get("complete")
            else "REPLAY_VERIFIED_PARTIAL_CONTINUOUS_OBSERVATIONS"
        ),
        lifecycle=lifecycle,
        source_directory=str(source),
        evidence=evidence,
        periods=rows,
        totals=totals,
        snapshots=snapshots,
        finance=dict(
            finance,
            capex=capex,
        ),
        setup_cash_coverage=_setup_cash_coverage(source, opening, capex),
        financial_provenance={metric: list(evidence) for metric in finance},
        capex_provenance=[
            dict(
                reference=str(source / f"service-receipt-{n}.json"),
                sha256=hashlib.sha256(
                    (source / f"service-receipt-{n}.json").read_bytes()
                ).hexdigest(),
            )
            for n in range(3)
            if (source / f"service-receipt-{n}.json").is_file()
        ],
        limitations=[
            "Monthly and quarterly intervals are bounded samples around native boundaries; "
            "they are not exact calendar-month accruals.",
            "Annual intervals use native economy-date anniversary targets, not 365-day years.",
            "Missing service attribution, costs, cycles and utilization remain UNKNOWN.",
            "Vehicle profit and annual running-cost rates do not establish "
            "actual operating expenses.",
        ],
    )
    if verified.get("offline_recovery") is not None:
        report["offline_recovery"] = verified["offline_recovery"]
        report["classification"] = "OFFLINE_RECOVERED_REPLAY_VERIFIED_CONTINUOUS_OBSERVATIONS"
        report["limitations"].append(
            "Historical native attempt remains FAILED; finalization metadata was derived offline."
        )
    return report


def render_continuous_html(report: dict) -> str:
    scopes = [row["scope"] for row in report["totals"]]
    service_scopes = [scope for scope in scopes if scope != "network"]
    labels = {scope: f"Service {index}" for index, scope in enumerate(service_scopes, 1)}
    labels["network"] = "Network"
    services = _services(report["snapshots"][0])
    legend = (
        "<h2>Service identities</h2><ul>"
        + "".join(
            f"<li>{labels[scope]}: <code>{escape(scope)}</code>; vehicle "
            f"{escape(str(services[scope].get('vehicle', 'UNKNOWN')))}</li>"
            for scope in service_scopes
        )
        + "<li>Network: all three services combined.</li></ul>"
    )
    charts = []
    for period, metric, title, unit in (
        ("monthly", "revenue", "Monthly revenue", "GBP"),
        ("annual", "delivered_cargo", "Annual delivered cargo", "cargo units"),
        ("monthly", "vehicle_operating_expenses", "Measured operating costs", "GBP"),
        (
            "monthly",
            "known_unallocated_expenses",
            "Observed company aggregate expenses (unallocated categories)",
            "GBP",
        ),
    ):
        charts.append(
            _bars(
                title,
                [
                    (f"{row['index']} {labels[row['scope']]}", row[metric], "#176b86")
                    for row in report["periods"]
                    if row["period"] == period
                ],
                unit,
            )
        )
    charts.append(
        _bars(
            "Service-level revenue comparison",
            [(labels[row["scope"]], row["revenue"], "#176b86") for row in report["totals"]],
            "GBP",
        )
    )
    selected = {report["snapshots"][0]["sequence"], report["snapshots"][-1]["sequence"]}
    selected.update(
        int(row["evidence_refs"][-1]) for row in report["periods"] if row["period"] == "monthly"
    )
    snapshots = [s for s in report["snapshots"] if s["sequence"] in selected]
    for title, field, unit in (
        ("Cash balance over time", "cash", "GBP"),
        ("Loan balance over time", "loan", "GBP"),
    ):
        charts.append(
            _bars(
                title,
                [(str(s["economy_date"]), s["finance"].get(field), "#176b86") for s in snapshots],
                unit,
            )
        )
    for title, field, unit in (
        ("Station cargo backlog", "station_waiting", "cargo units"),
        (
            "Derived sampled vehicle capacity utilization"
            if any("vehicle_telemetry" in s for s in snapshots)
            else "Measured vehicle capacity utilization",
            "capacity_utilization",
            "ratio",
        ),
    ):
        charts.append(
            _bars(
                title,
                [
                    (f"{s['economy_date']} {labels[scope]}", _metric(s, scope, field), "#176b86")
                    for s in snapshots
                    for scope in scopes
                ],
                unit,
            )
        )
    opening = snapshots[0]
    capex = report["finance"].get("capex")
    cumulative = []
    for snapshot in snapshots:
        cumulative.extend(
            [
                (
                    f"{snapshot['economy_date']} revenue",
                    _delta(
                        _metric(snapshot, "network", "revenue"),
                        _metric(opening, "network", "revenue"),
                    ),
                    "#176b86",
                ),
                (f"{snapshot['economy_date']} CAPEX", capex, "#b66a08"),
            ]
        )
    charts.append(_bars("Cumulative revenue vs CAPEX", cumulative, "GBP"))
    charts.append(
        _bars(
            "Break-even analysis",
            [
                (
                    "Verified break-even time",
                    report["finance"].get("break_even_economy_days"),
                    "#176b86",
                )
            ],
            "economy days",
        )
    )
    provenance = "".join(
        f'<li>Snapshot {escape(key)}: <a href="'
        f'{escape(Path(value["reference"]).as_uri(), quote=True)}">'
        f"{escape(value['reference'])}</a> · canonical SHA256 {value['sha256']} · "
        f"{escape(str(value['source_digests']))}</li>"
        for key, value in report["evidence"].items()
    )
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>P07 five-year freight</title>'
        "<style>body{font:16px system-ui;max-width:1100px;margin:auto;padding:24px}"
        "svg{width:100%;max-height:none}small,.axis{fill:#667}.unknown{fill:#955}</style>"
        "<h1>P07 continuous freight observations</h1><p>Economy dates, calendar dates, "
        "script ticks "
        "and wall-clock seconds remain separate. UNKNOWN is never zero. Charts use monthly sampled "
        "intervals; revenue beyond CAPEX alone does not prove profitability or break-even.</p>"
        + (
            "<p><strong>Historical native attempt: FAILED. Offline recovered evidence; "
            "derived metadata does not change the native terminal status.</strong></p>"
            if report.get("offline_recovery") is not None
            else ""
        )
        + (
            "<h2>Setup and operating cash coverage</h2><pre>"
            + escape(json.dumps(report["setup_cash_coverage"], indent=2))
            + "</pre>"
            if report.get("setup_cash_coverage") is not None
            else ""
        )
        + legend
        + "".join(charts)
        + "<h2>Limitations</h2><ul>"
        + "".join(f"<li>{escape(item)}</li>" for item in report["limitations"])
        + "</ul><h2>Evidence provenance</h2><ul>"
        + provenance
        + "</ul></html>"
    )


def analyze_continuous(
    source: Path, output: Path, *, recovery_directory: Path | None = None
) -> dict:
    from app.simulation.openttd.freight_continuous import verify_continuous_evidence

    source = source.resolve()
    destinations = [
        output,
        *(output / name for name in ("summary.json", "metrics.csv", "charts.html")),
    ]
    if any(path.resolve().is_relative_to(source) for path in destinations):
        raise ValueError("analysis output must not modify retained evidence")
    verified = (
        verify_continuous_evidence(source)
        if recovery_directory is None
        else verify_continuous_evidence(source, recovery_directory=recovery_directory)
    )
    report = summarize_continuous(verified, source)
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    with (output / "metrics.csv").open("w", newline="") as stream:
        rows = report["periods"]
        columns = list(rows[0]) if rows else ["period", "index", "scope", "evidence_refs"]
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    (output / "charts.html").write_text(render_continuous_html(report))
    return dict(output=str(output), periods=len(report["periods"]), lifecycle=report["lifecycle"])
