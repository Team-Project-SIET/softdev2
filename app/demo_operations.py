"""Read-only operational display over the existing serial executor's evidence.

No polling requests are sent to OpenTTD. Partial JSON writes are retried by the
viewer. P07 remains the authority for the final independently replayed report.
"""

import json
from html import escape
from pathlib import Path

from app.experiments.freight_analytics import _bars
from app.simulation.openttd.freight_delivery import (
    DeliveryPlan,
    DeliveryReadback,
    DeliveryRequest,
    verify_delivery,
    verify_snapshot,
)

MAX_SERVICES = 16


def _json(path: Path, limit: int = 16384):
    try:
        with path.open("rb") as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ValueError(f"operational evidence exceeds byte budget: {path.name}")
        return json.loads(raw)
    except FileNotFoundError, json.JSONDecodeError:
        return None


def _states(directory: Path, index: int):
    plan_data = _json(directory / f"native-plan-{index}.json")
    if plan_data is None:
        return []
    plan = DeliveryPlan.model_validate_json(json.dumps(plan_data))
    names = (
        [f"s{index}-read-{n}" for n in range(10)]
        + [f"s{index}-observe-{n}" for n in range(4)]
        + [f"s{index}-finish", f"s{index}-park-read"]
    )
    states = []
    for name in names:
        request = _json(directory / f"{name}-request.json")
        value = _json(directory / f"{name}-response.json")
        if request is None or value is None:
            continue
        readback = DeliveryReadback.parse_for(
            DeliveryRequest.model_validate_json(json.dumps(request)),
            json.dumps(value, separators=(",", ":")).encode(),
        )
        verify_snapshot(plan, readback)
        states.append((name, readback))
    return sorted(states, key=lambda row: (row[1].s[0], row[1].s[22]))


def operational_snapshot(directory: Path, count: int) -> dict:
    if not 0 <= count <= MAX_SERVICES:
        raise ValueError("operational service budget exceeded")
    metadata = _json(directory / "PRELAUNCH.json", 2 * 1024 * 1024) or {}
    map_width = metadata.get("world", {}).get("width", 64)
    services, completions, latest = [], [], []
    for index in range(count):
        states = _states(directory, index)
        receipt = _json(directory / f"service-receipt-{index}.json", 256 * 1024)
        if receipt is not None:
            records = dict(states)
            needed = [
                f"s{index}-read-8",
                *[f"s{index}-observe-{n}" for n in range(4)],
                f"s{index}-finish",
            ]
            if not all(name in records for name in needed):
                receipt = None  # Receipt publication can race the final response write.
            else:
                plan = DeliveryPlan.model_validate_json(
                    json.dumps(_json(directory / f"native-plan-{index}.json"))
                )
                verified = verify_delivery(
                    plan,
                    records[needed[0]],
                    [records[name] for name in needed[1:-1]],
                    records[needed[-1]],
                    map_width=map_width,
                )
                if any(
                    receipt.get(k) != verified[k]
                    for k in ("plan_digest", "vehicle", "delivered", "payment_income")
                ):
                    raise ValueError("operational receipt differs from replayed delivery")
        state = states[-1][1].s if states else None
        if state is not None:
            latest.append(state)
        status = "PLANNED"
        if state is not None:
            status = "CONSTRUCTING" if state[22] < 10 else "STOPPED" if state[9] == 1 else "RUNNING"
        if receipt is not None and state is not None:
            completions.append((records[f"s{index}-finish"].s[0], index, receipt))
        services.append(
            dict(
                service=index,
                status=status,
                vehicle=state[4] if state is not None and state[4] >= 0 else None,
                tick=state[0] if state is not None else None,
                delivered_cargo=receipt.get("delivered") if receipt else None,
                revenue_gbp=receipt.get("payment_income") if receipt else None,
                command_expenses_gbp=receipt.get("construction_purchase_spending")
                if receipt
                else None,
                cargo_backlog=state[15] if state is not None and state[16] >= 0 else None,
            )
        )
    points, cargo, revenue = [], 0, 0
    for tick, index, receipt in sorted(completions):
        cargo += receipt["delivered"]
        revenue += receipt["payment_income"]
        previous = points[-1] if points else None
        elapsed = tick - previous["tick"] if previous else None
        points.append(
            dict(
                tick=tick,
                service=index,
                cumulative_delivered_cargo=cargo,
                cumulative_revenue_gbp=revenue,
                throughput_cargo_per_script_tick=(cargo - previous["cumulative_delivered_cargo"])
                / elapsed
                if previous and elapsed and elapsed > 0
                else None,
                revenue_gbp_per_script_tick=(revenue - previous["cumulative_revenue_gbp"]) / elapsed
                if previous and elapsed and elapsed > 0
                else None,
            )
        )
    cash = max(latest, key=lambda s: s[0])[3] if latest else None
    expenses = [s["command_expenses_gbp"] for s in services]
    return dict(
        schema="demo-operational-history-v1",
        experiment_key=metadata.get("experiment_key"),
        experiment=metadata.get("experiment"),
        world=metadata.get("world"),
        execution_plan_digest=(_json(directory / "receipt.json", 4 * 1024 * 1024) or {}).get(
            "execution_plan_digest"
        ),
        evidence_basis=(
            "retained native readbacks and service receipts; final report replayed by P07"
        ),
        services=services,
        observed_company_cash_gbp=cash,
        observed_tick=max((s[0] for s in latest), default=None),
        derived_completed_delivered_cargo=cargo if completions else None,
        derived_completed_revenue_gbp=revenue if completions else None,
        derived_completed_command_expenses_gbp=sum(e for e in expenses if e is not None)
        if any(e is not None for e in expenses)
        else None,
        observed_vehicles=(
            len({s["vehicle"] for s in services if s["vehicle"] is not None}) if latest else None
        ),
        sampled_services=len(latest),
        derived_active_services=(
            sum(s["status"] == "RUNNING" for s in services) if latest else None
        ),
        derived_active_vehicles=(
            len(
                {
                    s["vehicle"]
                    for s in services
                    if s["status"] == "RUNNING" and s["vehicle"] is not None
                }
            )
            if latest
            else None
        ),
        points=points,
        measured_operating_expenses_gbp=None,
        profit_gbp=None,
        roi=None,
        trend_basis=(
            "DERIVED completion intervals in script ticks; serial batch operation, not steady state"
        ),
    )


def terminal_status(snapshot: dict) -> str:
    def known(value):
        return "UNKNOWN" if value is None else str(value)

    lines = [
        f"OBSERVED vehicles seen={known(snapshot['observed_vehicles'])}; "
        f"cash GBP {known(snapshot['observed_company_cash_gbp'])}; "
        f"latest retained tick={known(snapshot['observed_tick'])}; "
        f"DERIVED sampled active services={known(snapshot['derived_active_services'])}; "
        f"active vehicles={known(snapshot['derived_active_vehicles'])}; "
        f"sampled services={snapshot['sampled_services']}/{len(snapshot['services'])}",
        f"DERIVED completed cargo={known(snapshot['derived_completed_delivered_cargo'])}; "
        f"revenue GBP {known(snapshot['derived_completed_revenue_gbp'])}; "
        "measured command expenses GBP "
        f"{known(snapshot['derived_completed_command_expenses_gbp'])}",
        "Operating expenses / profit / ROI: UNKNOWN",
    ]
    for service in snapshot["services"]:
        lines.append(
            f"  Service {service['service'] + 1}: {service['status']}; "
            f"vehicle={known(service['vehicle'])}; "
            f"OBSERVED backlog={known(service['cargo_backlog'])}"
        )
    return "\n".join(lines)


def write_operational_report(directory: Path, output: Path, count: int):
    """Call after P07 replay succeeds. Source evidence is never edited."""
    snapshot = operational_snapshot(directory, count)
    (output / "operational-history.json").write_text(json.dumps(snapshot, indent=2) + "\n")
    points = snapshot["points"]
    charts = []
    for title, field, unit in (
        ("Revenue at delivery milestones", "cumulative_revenue_gbp", "GBP"),
        ("Delivered cargo at delivery milestones", "cumulative_delivered_cargo", "cargo units"),
        (
            "Throughput between delivery milestones",
            "throughput_cargo_per_script_tick",
            "cargo/tick",
        ),
        ("Revenue between delivery milestones", "revenue_gbp_per_script_tick", "GBP/tick"),
    ):
        charts.append(
            _bars(title, [(f"tick {p['tick']}", p[field], "#2473ab") for p in points], unit)
        )
    html = (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        "<title>OpenTTD operational results</title>"
        "<style>body{font:16px sans-serif;max-width:1000px;margin:2em auto}"
        "svg{width:100%}text{font:14px sans-serif}.unknown{fill:#777}</style>"
        "<h1>Operational results</h1><pre>" + escape(terminal_status(snapshot)) + "</pre>"
        "<p>" + escape(snapshot["trend_basis"]) + "</p>"
        "<p>OBSERVED: native state and receipt measurements. DERIVED: sums and milestone rates. "
        "UNKNOWN: unsampled intervals, full operating expenses, profit and ROI. "
        "Backlog is a point sample of station waiting cargo, not unmet demand. "
        "Cash and service states are asynchronous; see per-service ticks in JSON.</p>"
        + "".join(charts)
        + "</html>"
    )
    (output / "operations.html").write_text(html)
    return snapshot


def compare_operational_reports(directories: list[Path], output: Path):
    """Descriptive seed/configuration comparison; no pooled ROI or causal claim."""
    from hashlib import sha256

    if not 2 <= len(directories) <= 16:
        raise ValueError("comparison requires 2..16 P07 report directories")
    rows = []
    for directory in directories:
        history = _json(directory / "operational-history.json", 1024 * 1024)
        evaluation = _json(directory / "evaluation.json", 1024 * 1024)
        if (
            history is None
            or evaluation is None
            or evaluation.get("classification") != "NATIVE_MULTI_SERVICE_EVALUATION"
        ):
            raise ValueError("comparison requires completed P07 operational reports")
        rows.append(
            dict(
                report=str(directory.resolve()),
                evaluation_sha256=sha256((directory / "evaluation.json").read_bytes()).hexdigest(),
                history_sha256=sha256(
                    (directory / "operational-history.json").read_bytes()
                ).hexdigest(),
                experiment_key=history["experiment_key"],
                experiment=history["experiment"],
                world=history["world"],
                plan=history["execution_plan_digest"],
                delivered_cargo=history["derived_completed_delivered_cargo"],
                revenue_gbp=history["derived_completed_revenue_gbp"],
                command_expenses_gbp=history["derived_completed_command_expenses_gbp"],
                company_cash_gbp=history["observed_company_cash_gbp"],
                operating_expenses_gbp=None,
                profit_gbp=None,
                roi=None,
            )
        )
    policy = (
        "Descriptive reports only. Seeds/configurations may differ. "
        "Serial batch durations and cargo mixes differ; no causal or profitability claim."
    )
    result = dict(
        schema="demo-comparison-v1",
        classification="DERIVED",
        runs=rows,
        comparison_policy=policy,
    )
    output.mkdir(parents=True, exist_ok=False)
    (output / "comparison.json").write_text(json.dumps(result, indent=2) + "\n")
    charts = []
    for field, unit in (
        ("delivered_cargo", "cargo units"),
        ("revenue_gbp", "GBP"),
        ("command_expenses_gbp", "GBP"),
    ):
        charts.append(
            _bars(
                field, [(f"Run {n + 1}", row[field], "#2473ab") for n, row in enumerate(rows)], unit
            )
        )
    (output / "comparison.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Demo comparison</title>'
        "<style>body{font:16px sans-serif;max-width:1000px;margin:2em auto}svg{width:100%}</style>"
        "<h1>DERIVED seed/configuration comparison</h1><p>"
        + escape(policy)
        + "</p>"
        + "".join(charts)
        + "</html>"
    )
    return result
