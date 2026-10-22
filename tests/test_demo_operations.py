"""Operational reader checked against the existing controlled GameScript peer."""

import json

import pytest

from app.demo_operations import operational_snapshot, terminal_status, write_operational_report
from app.simulation.openttd.freight_delivery import DeliveryRequest, verify_delivery
from tests.test_freight_delivery import complete, delivery_vm


def retained_batch(directory, index=0, tick_offset=0):
    plan, baseline, observations, final = complete(delivery_vm())
    # Correlate request names while preserving all native measurements.
    rows = [
        ("read-8", baseline),
        *[(f"observe-{n}", r) for n, r in enumerate(observations)],
        ("finish", final),
    ]
    changed = []
    for suffix, record in rows:
        name = f"s{index}-{suffix}"
        state = list(record.s)
        state[0] += tick_offset
        state[26] += tick_offset
        r = record.model_copy(update={"request_id": name, "s": tuple(state)})
        q = DeliveryRequest(op=r.op, request_id=name, plan=plan.digest, arg=r.arg)
        (directory / f"{name}-request.json").write_bytes(q.to_bytes())
        (directory / f"{name}-response.json").write_text(r.model_dump_json())
        changed.append(r)
    (directory / f"native-plan-{index}.json").write_text(plan.model_dump_json())
    receipt = verify_delivery(plan, changed[0], changed[1:-1], changed[-1])
    receipt["construction_purchase_spending"] = 1000
    (directory / f"service-receipt-{index}.json").write_text(json.dumps(receipt))


def test_unknown_is_not_zero_and_zero_services_is_supported(tmp_path):
    result = operational_snapshot(tmp_path, 0)
    assert result["derived_completed_revenue_gbp"] is None
    assert result["observed_company_cash_gbp"] is None
    assert "UNKNOWN" in terminal_status(result)
    with pytest.raises(ValueError, match="budget"):
        operational_snapshot(tmp_path, 17)


def test_delivery_replay_status_history_and_charts(tmp_path):
    retained_batch(tmp_path)
    retained_batch(tmp_path, 1, 100)
    result = operational_snapshot(tmp_path, 2)
    assert result["derived_completed_delivered_cargo"] == 40
    assert result["derived_completed_revenue_gbp"] == 1000
    assert result["derived_completed_command_expenses_gbp"] == 2000
    assert result["points"][0]["throughput_cargo_per_script_tick"] is None
    assert result["points"][1]["throughput_cargo_per_script_tick"] == 0.2
    assert result["measured_operating_expenses_gbp"] is None
    assert all(s["vehicle"] is not None for s in result["services"])
    output = tmp_path / "report"
    output.mkdir()
    write_operational_report(tmp_path, output, 2)
    assert "<svg" in (output / "operations.html").read_text()
    assert json.loads((output / "operational-history.json").read_text()) == result


def test_mutated_receipt_and_plan_mismatch_fail_closed(tmp_path):
    retained_batch(tmp_path)
    path = tmp_path / "service-receipt-0.json"
    value = json.loads(path.read_text())
    value["payment_income"] += 1
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="differs"):
        operational_snapshot(tmp_path, 1)


def test_partial_response_is_unknown_until_complete(tmp_path):
    retained_batch(tmp_path)
    (tmp_path / "s0-finish-response.json").write_text('{"protocol":')
    result = operational_snapshot(tmp_path, 1)
    assert result["derived_completed_revenue_gbp"] is None


def test_comparison_keeps_world_metadata_and_unknown_costs(tmp_path):
    from app.demo_operations import compare_operational_reports

    reports = []
    for index in range(2):
        source = tmp_path / f"source-{index}"
        source.mkdir()
        retained_batch(source)
        (source / "PRELAUNCH.json").write_text(
            json.dumps(
                dict(
                    world=dict(seed=index, width=64, height=64),
                    experiment_key=str(index),
                    experiment=dict(seed=index),
                )
            )
        )
        output = tmp_path / f"report-{index}"
        output.mkdir()
        write_operational_report(source, output, 1)
        (output / "evaluation.json").write_text(
            json.dumps(dict(classification="NATIVE_MULTI_SERVICE_EVALUATION"))
        )
        reports.append(output)
    result = compare_operational_reports(reports, tmp_path / "comparison")
    assert [r["world"]["seed"] for r in result["runs"]] == [0, 1]
    assert all(
        r["operating_expenses_gbp"] is None and r["profit_gbp"] is None for r in result["runs"]
    )
    assert (tmp_path / "comparison/comparison.html").is_file()


def test_planned_services_without_readbacks_have_unknown_counts(tmp_path):
    snapshot = operational_snapshot(tmp_path, 3)
    assert snapshot["observed_vehicles"] is None
    assert snapshot["derived_active_services"] is None
    assert snapshot["derived_active_vehicles"] is None
    assert "vehicles seen=UNKNOWN" in terminal_status(snapshot)
    assert "sampled services=0/3" in terminal_status(snapshot)


def test_trend_timestamp_is_delivery_boundary_not_later_park_sample(tmp_path):
    from app.simulation.openttd.freight_delivery import DeliveryReadback

    retained_batch(tmp_path)
    final = DeliveryReadback.model_validate_json(
        (tmp_path / "s0-finish-response.json").read_bytes()
    )
    state = list(final.s)
    state[0] += 100
    state[9] = 1
    parked = final.model_copy(
        update={"op": "read", "request_id": "s0-park-read", "status": "READ", "s": tuple(state)}
    )
    request = DeliveryRequest(op="read", request_id="s0-park-read", plan=final.plan)
    (tmp_path / "s0-park-read-request.json").write_bytes(request.to_bytes())
    (tmp_path / "s0-park-read-response.json").write_text(parked.model_dump_json())
    snapshot = operational_snapshot(tmp_path, 1)
    assert snapshot["points"][0]["tick"] == final.s[0]
    assert snapshot["services"][0]["tick"] == final.s[0] + 100
