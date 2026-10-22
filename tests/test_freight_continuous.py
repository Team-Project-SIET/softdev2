"""Controlled native economy-clock lineage and resource contracts; no launches."""

import json

import pytest

from app.simulation.openttd.freight_continuous import (
    MAX_POLLS,
    MONITOR_SECONDS,
    EconomyProgress,
    _durable_append,
    monitoring_budgets,
    period_reports,
)
from app.simulation.openttd.proof.freight_delivery import network_budgets, staged_package


def clock(day, year, month, dom=1):
    return dict(
        economy_date=day,
        economy_year=year,
        economy_month=month,
        economy_day=dom,
        script_tick=day * 74,
        paused=False,
    )


def test_calendar_native_five_year_anniversaries_include_leap_year():
    baseline = clock(0, 2000, 1)
    targets = [366, 731, 1096, 1461, 1827]
    progress = EconomyProgress(baseline, targets)
    # Daily reports exercise all month/quarter boundaries without skipping months.
    from datetime import date, timedelta

    flags = []
    for day in range(1, 1828):
        native = date(2000, 1, 1) + timedelta(days=day)
        flags.append(progress.observe(clock(day, native.year, native.month, native.day)))
    assert progress.annual_count == 5
    assert sum(f["monthly"] for f in flags) == 60
    assert sum(f["quarterly"] for f in flags) == 20
    assert sum(f["annual"] for f in flags) == 5


def test_wallclock_native_360_day_year_uses_native_anniversaries():
    baseline = clock(720000, 2000, 1)
    targets = [720000 + 360 * n for n in range(1, 6)]
    snapshots = [baseline | dict(annual_targets=targets)]
    for day in range(1, 1801):
        snapshots.append(
            clock(720000 + day, 2000 + day // 360, (day % 360) // 30 + 1, day % 30 + 1)
        )
    reports = period_reports(snapshots)
    assert reports["complete"]
    assert [len(reports[k]) for k in ("monthly", "quarterly", "annual")] == [60, 20, 5]
    assert reports["annual"][-1]["economy_date"] - baseline["economy_date"] == 1800


def test_no_duplicate_reporting_when_dates_repeat():
    baseline = clock(0, 1950, 1)
    progress = EconomyProgress(baseline, [365, 730, 1096, 1461, 1826])
    assert not any(progress.observe(baseline).values())
    assert progress.observe(clock(31, 1950, 2)) == dict(monthly=True, quarterly=False, annual=False)
    assert not any(progress.observe(clock(31, 1950, 2)).values())


@pytest.mark.parametrize(
    "bad", [clock(-1, 1950, 1), clock(3, 1950, 3), clock(1, 1950, 1) | {"paused": True}]
)
def test_invalid_clock_stops_monitoring(bad):
    progress = EconomyProgress(clock(0, 1950, 1), [365, 730, 1096, 1461, 1826])
    with pytest.raises(ValueError):
        progress.observe(bad)


def test_interrupted_partial_evidence_is_durable(tmp_path):
    journal = tmp_path / "continuous-snapshots.jsonl"
    row = {"sequence": 0, "economy_date": 1, "services": []}
    _durable_append(journal, row)
    assert json.loads(journal.read_text()) == row
    assert not (tmp_path / "continuous-summary.json").exists()


def test_continuous_finite_budget_and_existing_one_shot_unchanged():
    budget = network_budgets(3, 5)
    assert budget["requests"] == 87 + 1 + 4 * MAX_POLLS
    assert budget["monitor_seconds"] == MONITOR_SECONDS
    assert budget["total_seconds"] > MONITOR_SECONDS > 3600
    assert budget["monitor_poll_seconds"] == 2
    assert budget["mutations"] == 30
    assert network_budgets(3)["requests"] == 87
    assert monitoring_budgets()["monitor_artifact_bytes"] > 0
    with pytest.raises(ValueError):
        network_budgets(2, 5)


def test_continuous_staging_only_adds_opt_in_subclass():
    normal = staged_package(True, True, True, "high-budget-500k", 3)
    continuous = staged_package(True, True, True, "high-budget-500k", 3, 5)
    assert b"class NetworkFreightProof" in normal["main.nut"]
    assert b"class ContinuousFreightProof" in continuous["main.nut"]
    assert b"function NetworkHandle(q)" in continuous["continuous-parent.nut"]
    assert b'"ContinuousFreightProof"' in continuous["info.nut"]
    assert b"function LoadService(n)" in continuous["continuous-parent.nut"]


def _controlled_network():
    from app.simulation.openttd.freight_delivery import DeliveryPlan

    plans = []
    receipts = []
    for n in range(3):
        plans.append(
            DeliveryPlan(
                prelaunch_digest="a" * 64,
                source_save_digest="b" * 64,
                admission_digest="c" * 64,
                a=(n, n + 3, 3, 8, 100 + n, 101 + n, 200 + n, 201 + n, 99 + n, 300 + n),
                f=(0, 0, 0, 0, 100, 20, 100, 1),
            )
        )
        receipts.append(dict(vehicle=n, route_id=f"route-{n}", construction_purchase_spending=100))
    return plans, receipts


def _controlled_exchange(tmp_path, plans, *, fail_after=None, unhealthy=False):
    from app.simulation.openttd.freight_continuous import native_economy_ordinal
    from app.simulation.openttd.freight_finance import ContinuousReadback

    calls = []

    def native_clock(day):
        return dict(
            economy_date=720000 + day,
            economy_year=2000 + day // 360,
            economy_month=(day % 360) // 30 + 1,
            economy_day=day % 30 + 1,
            calendar_date=None,
            timekeeping_units=1,
            script_tick=day * 74,
            paused=False,
        )

    def state(n, day):
        p = plans[n]
        s = [0] * 30
        s[0] = day * 74
        s[1] = 720000 + day
        s[3] = 500000 + day * 90
        s[4] = n
        s[5] = 0
        s[6] = 8
        s[7] = 20
        s[8] = 100 + n + day
        s[9] = 1 if unhealthy and day else 0
        s[11] = 10
        s[12] = 2
        s[13] = p.a[4]
        s[14] = p.a[6]
        s[15] = day
        s[16] = n
        s[17] = n + 3
        s[20] = day * 10
        s[22] = 10
        s[28] = s[29] = 1
        return s

    def company(day):
        return dict(
            cash=500000 + day * 90,
            loan_balance=0,
            quarter_income=(day % 90) * 100,
            quarter_expenses=-(day % 90) * 10,
            quarter_delivered=(day % 90) * 60,
            previous_quarter_income=9000 if day else 0,
            previous_quarter_expenses=-900 if day else 0,
            previous_quarter_delivered=5400 if day else 0,
            loan_interest=None,
            expense_categories=None,
            vehicle_operating_expenses=None,
        )

    async def exchange(session, q, directory, **kwargs):
        calls.append(q.request_id)
        (directory / f"{q.request_id}-request.json").write_bytes(q.to_bytes())
        if fail_after is not None and len(calls) > fail_after:
            raise ConnectionError("controlled interruption")
        day = 0 if q.type == "continuous-begin" else int(q.request_id.split("-")[1]) * 30
        value = dict(
            protocol=1,
            type=q.type + "-result",
            request_id=q.request_id,
            status="ok",
            clock=native_clock(day),
        )
        if q.type == "continuous-begin":
            value.update(
                company(0),
                annual_targets=[native_economy_ordinal(2000 + n, 1, 1, 1) for n in range(1, 6)],
                start_economy_date=720000,
                baseline_snapshots=[state(n, 0) for n in range(3)],
                baseline_delivered=[0] * 3,
            )
        elif q.type == "continuous-company":
            value.update(company(day))
        else:
            n = q.service
            value.update(
                service=n,
                plan=plans[n].digest,
                vehicle=n,
                snapshot=state(n, day),
                profit_this_year=day * 10,
                profit_last_year=0,
                running_cost_rate_per_year=100,
                delivered=day * 20,
                revenue=None,
                operating_costs=None,
                completed_delivery_cycles=None,
                station_waiting_cargo=day,
                cargo_load=10,
                capacity=20,
            )
        raw = json.dumps(value, separators=(",", ":")).encode()
        (directory / f"{q.request_id}-response.json").write_bytes(raw)
        from app.simulation.openttd.admin_protocol import encode_admin_frame
        from app.simulation.openttd.gamescript_transport import SERVER_GAMESCRIPT, encode_gamescript

        if session._frame_observer is not None:
            session._frame_observer("outbound", encode_gamescript(q.to_bytes()))
            session._frame_observer("inbound", encode_admin_frame(SERVER_GAMESCRIPT, raw + b"\0"))
        return ContinuousReadback.parse_for(q, raw)

    return exchange, calls


def test_async_five_year_lifecycle_repeated_deliveries(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from app.simulation.openttd import freight_continuous as continuous
    from app.simulation.openttd.proof import freight_delivery as proof

    plans, receipts = _controlled_network()
    exchange, calls = _controlled_exchange(tmp_path, plans)
    monkeypatch.setattr(proof, "exchange", exchange)

    async def paced(seconds):
        assert seconds == 2

    monkeypatch.setattr(continuous.asyncio, "sleep", paced)
    logs = tmp_path / "logs"
    logs.mkdir()
    prepared = SimpleNamespace(
        directory=tmp_path, spec=SimpleNamespace(workspace=SimpleNamespace(logs=logs))
    )

    frames = []

    def original(d, f):
        frames.append((d, f.hex()))

    session = SimpleNamespace(_frame_observer=original)
    result = {"requests": 66}
    summary = asyncio.run(
        continuous.monitor_network(
            prepared, session, plans, receipts, {"budgets": network_budgets(3, 5)}, result
        )
    )
    assert summary["complete_economy_years"] == 5
    assert summary["observation_counts"] == dict(monthly=60, quarterly=20, annual=5)
    assert summary["financial_metrics"]["delivered_cargo"] == 108000
    assert summary["financial_metrics"]["freight_revenue"] == 180000
    assert summary["financial_metrics"]["vehicle_operating_expenses"] is None
    assert result["requests"] == 66 + 1 + 60 * 4
    assert len(calls) == 241
    assert session._frame_observer is original
    journal = [
        json.loads(line)
        for line in (tmp_path / "continuous-snapshots.jsonl").read_text().splitlines()
    ]
    assert journal[0]["elapsed_economy_days"] == 0
    assert journal[-1]["services"][0]["delivered"] == 36000
    assert journal[-1]["elapsed_economy_days"] == 1800
    (tmp_path / "frames.json").write_text(json.dumps(frames))
    for n, plan in enumerate(plans):
        (tmp_path / f"native-plan-{n}.json").write_text(plan.model_dump_json())
        (tmp_path / f"service-receipt-{n}.json").write_text(json.dumps(receipts[n]))
    replay = continuous.verify_continuous_evidence(tmp_path, _full=False)
    assert replay["complete"]
    assert len(list(tmp_path.glob("continuous-monthly-*.json"))) == 60
    assert len(list(tmp_path.glob("continuous-quarterly-*.json"))) == 20
    assert len(list(tmp_path.glob("continuous-annual-*.json"))) == 5
    original_request = (tmp_path / "continuous-begin-request.json").read_bytes()
    (tmp_path / "continuous-begin-request.json").write_bytes(
        original_request.replace(b"continuous-begin", b"continuous-other")
    )
    with pytest.raises(ValueError, match="begin request changed"):
        continuous.verify_continuous_evidence(tmp_path, _full=False)
    (tmp_path / "continuous-begin-request.json").write_bytes(original_request)
    frames[2], frames[4] = frames[4], frames[2]
    (tmp_path / "frames.json").write_text(json.dumps(frames))
    with pytest.raises(ValueError, match="secure request order mismatch"):
        continuous.verify_continuous_evidence(tmp_path, _full=False)


@pytest.mark.parametrize("fail_after", [0, 1, 6])
def test_async_interruption_retains_prefix_and_restores_observer(tmp_path, monkeypatch, fail_after):
    import asyncio
    from types import SimpleNamespace

    from app.simulation.openttd import freight_continuous as continuous
    from app.simulation.openttd.proof import freight_delivery as proof

    plans, receipts = _controlled_network()
    exchange, _ = _controlled_exchange(tmp_path, plans, fail_after=fail_after)
    monkeypatch.setattr(proof, "exchange", exchange)

    async def paced(seconds):
        pass

    monkeypatch.setattr(continuous.asyncio, "sleep", paced)
    logs = tmp_path / "logs"
    logs.mkdir()
    prepared = SimpleNamespace(
        directory=tmp_path, spec=SimpleNamespace(workspace=SimpleNamespace(logs=logs))
    )

    def original(d, f):
        pass

    session = SimpleNamespace(_frame_observer=original)
    with pytest.raises(ConnectionError, match="controlled interruption"):
        asyncio.run(
            continuous.monitor_network(
                prepared,
                session,
                plans,
                receipts,
                {"budgets": network_budgets(3, 5)},
                {"requests": 66},
            )
        )
    assert session._frame_observer is original
    partial = json.loads((tmp_path / "continuous-partial.json").read_text())
    assert partial["snapshots"] == (0 if fail_after == 0 else 1 if fail_after == 1 else 2)
    assert partial["automatic_resume"] is False
    assert not (tmp_path / "continuous-summary.json").exists()


def test_async_invalid_health_stops_and_preserves_baseline(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from app.simulation.openttd import freight_continuous as continuous
    from app.simulation.openttd.proof import freight_delivery as proof

    plans, receipts = _controlled_network()
    exchange, _ = _controlled_exchange(tmp_path, plans, unhealthy=True)
    monkeypatch.setattr(proof, "exchange", exchange)

    async def paced(seconds):
        pass

    monkeypatch.setattr(continuous.asyncio, "sleep", paced)
    logs = tmp_path / "logs"
    logs.mkdir()
    prepared = SimpleNamespace(
        directory=tmp_path, spec=SimpleNamespace(workspace=SimpleNamespace(logs=logs))
    )
    session = SimpleNamespace(_frame_observer=None)
    with pytest.raises(ValueError, match="destroyed, stopped or identity changed"):
        asyncio.run(
            continuous.monitor_network(
                prepared,
                session,
                plans,
                receipts,
                {"budgets": network_budgets(3, 5)},
                {"requests": 66},
            )
        )
    assert json.loads((tmp_path / "continuous-partial.json").read_text())["snapshots"] == 1


def test_native_calendar_ordinal_and_february_anniversary_normalization():
    from app.simulation.openttd.freight_continuous import native_economy_ordinal

    assert native_economy_ordinal(2001, 2, 29, 0) == native_economy_ordinal(2001, 3, 1, 0)
    assert native_economy_ordinal(2000, 3, 1, 0) - native_economy_ordinal(2000, 2, 28, 0) == 2
    assert native_economy_ordinal(2001, 3, 1, 0) - native_economy_ordinal(2001, 2, 28, 0) == 1
    baseline = clock(720000, 2000, 1) | dict(timekeeping_units=1)
    progress = EconomyProgress(baseline, [720000 + 360 * n for n in range(1, 6)])
    with pytest.raises(ValueError, match="date and YMD disagree"):
        progress.observe(clock(720001, 2000, 2) | dict(timekeeping_units=1))


def test_async_poll_budget_exhaustion_is_partial(tmp_path, monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from app.simulation.openttd import freight_continuous as continuous
    from app.simulation.openttd.proof import freight_delivery as proof

    plans, receipts = _controlled_network()
    exchange, calls = _controlled_exchange(tmp_path, plans)
    monkeypatch.setattr(proof, "exchange", exchange)
    monkeypatch.setattr(continuous, "MAX_POLLS", 1)

    async def paced(seconds):
        pass

    monkeypatch.setattr(continuous.asyncio, "sleep", paced)
    logs = tmp_path / "logs"
    logs.mkdir()
    prepared = SimpleNamespace(
        directory=tmp_path, spec=SimpleNamespace(workspace=SimpleNamespace(logs=logs))
    )
    with pytest.raises(ValueError, match="finite continuous polling budget exhausted"):
        asyncio.run(
            continuous.monitor_network(
                prepared,
                SimpleNamespace(_frame_observer=None),
                plans,
                receipts,
                {"budgets": network_budgets(3, 5)},
                {"requests": 66},
            )
        )
    assert len(calls) == 5
    assert json.loads((tmp_path / "continuous-partial.json").read_text())["snapshots"] == 2
    assert not (tmp_path / "continuous-summary.json").exists()


def test_pending_secure_frame_storage_counts_toward_durable_budget(tmp_path):
    from app.simulation.openttd.freight_continuous import MAX_ARTIFACT_BYTES, _resource_check

    with pytest.raises(ValueError, match="artifact byte budget exhausted"):
        _resource_check(tmp_path, tmp_path, MAX_ARTIFACT_BYTES // 2 + 1)
