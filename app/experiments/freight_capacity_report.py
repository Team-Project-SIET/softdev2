"""Small P07 companion for controlled allocations, without simulated performance."""

from html import escape

from app.experiments.freight_analytics import _bars


def render_capacity_report(comparison: dict) -> str:
    queues = comparison["monthly_queue_samples"]
    chart = _bars(
        "Mean monthly sampled source queue",
        [(q["service"], q["mean_sampled_queue"], "#176b86") for q in queues],
        "cargo units",
    )
    rows = []
    for arm in comparison["configurations"]:
        allocation = str(arm.get("allocation", "infeasible"))
        capex = arm.get("estimated_capex_gbp", "UNKNOWN")
        rows.append(
            "<tr>"
            + "".join(
                f"<td>{escape(str(value))}</td>"
                for value in (arm["configuration"], allocation, capex, "UNKNOWN", "UNKNOWN")
            )
            + "</tr>"
        )
    blockers = "".join(f"<li>{escape(item)}</li>" for item in comparison["readiness_blockers"])
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        "<title>Controlled freight capacity comparison</title>"
        "<style>body{font-family:system-ui;max-width:1000px;margin:2rem auto}"
        "svg{width:100%}td,th{padding:.5rem;text-align:left}</style>"
        "<h1>Controlled freight capacity comparison</h1>"
        "<p>Historical Attempt 19 remains FAILED; baseline evidence was verified offline. "
        "A/B/C are planning configurations. No treatment throughput or revenue is measured.</p>"
        '<p><a href="charts.html">Existing P07 charts</a> | '
        '<a href="capacity-experiment.json">Inputs, plans and acceptance criteria</a></p>'
        + chart
        + "<p>Endpoint means describe sampled queues, "
        "not continuous queue exposure or marginal gains.</p>"
        "<table><tr><th>Arm</th><th>Vehicles by service</th><th>Estimated P05 CAPEX (GBP)</th>"
        "<th>Treatment cargo</th><th>Treatment revenue</th></tr>"
        + "".join(rows)
        + "</table><h2>Native readiness blockers</h2><ul>"
        + blockers
        + "</ul></html>"
    )
