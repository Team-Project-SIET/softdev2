"""Finite five-year monitoring on the existing secure freight session.

GSDate uses native economy time, including leap years or 360-day wallclock years.
Anniversaries are computed inside OpenTTD, never from a 365-day assumption.
"""

import asyncio
import json
import os
import time
from pathlib import Path

from app.simulation.openttd.proof.harness import sha256, write_json

MAX_POLLS = 3600
POLL_SECONDS = 2
MONITOR_SECONDS = 7200
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_LOG_BYTES = 8 * 1024 * 1024


def monitoring_budgets(telemetry_vehicle_count=0):
    if telemetry_vehicle_count not in (0, 3, 4):
        raise ValueError("invalid telemetry fleet size")
    requests = 87 + 1 + 4 * MAX_POLLS + telemetry_vehicle_count * (MAX_POLLS + 1)
    return dict(
        requests=requests,
        mutations=30,
        total_seconds=8400,
        monitor_seconds=MONITOR_SECONDS,
        monitor_polls=MAX_POLLS,
        monitor_poll_seconds=POLL_SECONDS,
        monitor_stall_seconds=120,
        monitor_vehicle_stall_seconds=300,
        monitor_frame_bytes=MAX_ARTIFACT_BYTES,
        monitor_frames=2 * requests + 4096,
        monitor_artifact_bytes=MAX_ARTIFACT_BYTES,
        monitor_log_bytes=MAX_LOG_BYTES,
    )


def native_economy_ordinal(year, month, day, units):
    if units == 1:
        return year * 360 + (month - 1) * 30 + day - 1
    if units != 0:
        raise ValueError("unknown native economy timekeeping units")
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    lengths = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return (
        year * 365
        + (year + 3) // 4
        - (year + 99) // 100
        + (year + 399) // 400
        + sum(lengths[: month - 1])
        + day
        - 1
    )


def validate_native_clock(clock):
    units = clock.get("timekeeping_units")
    if units is None:
        return  # Pure progression fixtures; native readback model requires this field.
    if clock["economy_date"] != native_economy_ordinal(
        clock["economy_year"], clock["economy_month"], clock["economy_day"], units
    ):
        raise ValueError("native economy date and YMD disagree")


class EconomyProgress:
    """Validate sampled native clock lineage and select nonduplicated periods."""

    def __init__(self, baseline, targets):
        if len(targets) != 5 or any(
            b <= a for a, b in zip([baseline["economy_date"]] + targets, targets)
        ):
            raise ValueError("five ordered native economy anniversaries required")
        validate_native_clock(baseline)
        if baseline.get("timekeeping_units") is not None and targets != [
            native_economy_ordinal(
                baseline["economy_year"] + n,
                baseline["economy_month"],
                baseline["economy_day"],
                baseline["timekeeping_units"],
            )
            for n in range(1, 6)
        ]:
            raise ValueError("native anniversary conversion mismatch")
        self.baseline = baseline
        self.targets = targets
        self.previous = baseline
        self.annual_count = 0

    def observe(self, clock):
        validate_native_clock(clock)
        old = self.previous
        if clock.get("timekeeping_units") != old.get("timekeeping_units"):
            raise ValueError("economy timekeeping units changed")
        if (
            clock["paused"]
            or clock["economy_date"] < old["economy_date"]
            or clock["script_tick"] < old["script_tick"]
        ):
            raise ValueError("paused or regressed economy clock")
        month = clock["economy_year"] * 12 + clock["economy_month"] - 1
        previous_month = old["economy_year"] * 12 + old["economy_month"] - 1
        if not 0 <= month - previous_month <= 1:
            raise ValueError("economy reporting month skipped or regressed")
        annual = False
        if self.annual_count < 5 and clock["economy_date"] >= self.targets[self.annual_count]:
            self.annual_count += 1
            annual = True
            if self.annual_count < 5 and clock["economy_date"] >= self.targets[self.annual_count]:
                raise ValueError("economy anniversary skipped")
        self.previous = clock
        return dict(
            monthly=month != previous_month,
            quarterly=month // 3 != previous_month // 3,
            annual=annual,
        )


def period_reports(snapshots):
    if not snapshots:
        raise ValueError("missing continuous baseline")
    progress = EconomyProgress(snapshots[0], snapshots[0]["annual_targets"])
    reports = dict(monthly=[], quarterly=[], annual=[])
    for snapshot in snapshots[1:]:
        flags = progress.observe(snapshot)
        for flag, key in [("monthly", "monthly"), ("quarterly", "quarterly"), ("annual", "annual")]:
            if flags[flag]:
                reports[key].append(snapshot)
    return reports | dict(complete=progress.annual_count == 5)


def _durable_append(path, value):
    with path.open("a") as stream:
        stream.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _resource_check(directory, logs, frame_bytes=0):
    if (
        sum(
            p.stat().st_size
            for p in directory.iterdir()
            if p.is_file() and p.suffix in (".json", ".jsonl")
        )
        + 2 * frame_bytes
        > MAX_ARTIFACT_BYTES
    ):
        raise ValueError("continuous artifact byte budget exhausted")
    if sum(p.stat().st_size for p in logs.glob("*.log")) > MAX_LOG_BYTES:
        raise ValueError("continuous log byte budget exhausted")


def _service_value(readback, plan, receipt):
    from app.simulation.openttd.freight_delivery import DeliveryReadback, verify_snapshot

    value = readback if isinstance(readback, dict) else readback.model_dump(mode="json")
    snapshot = value["snapshot"]
    state = DeliveryReadback(
        protocol=1,
        op="read",
        request_id="continuous-health",
        plan=plan.digest,
        arg=0,
        max_cost=100000,
        status="READ",
        a=plan.a,
        f=plan.f,
        s=tuple(snapshot),
        e=(),
    )
    verify_snapshot(plan, state)
    if (
        value["plan"] != plan.digest
        or value["vehicle"] != receipt["vehicle"]
        or snapshot[22] != 10
        or snapshot[9] == 1
    ):
        raise ValueError("continuous vehicle destroyed, stopped or identity changed")
    value["route_id"] = receipt["route_id"]
    value["capacity_utilization"] = (
        value["cargo_load"] / value["capacity"] if value["capacity"] > 0 else None
    )
    return value


def _baseline_snapshot(begin, plans, receipts, wall_elapsed_seconds):
    value = begin.model_dump(mode="json")
    clock = value["clock"]
    states = value["baseline_snapshots"]
    delivered = value["baseline_delivered"]
    if states is None or delivered is None or len(states) != 3 or len(delivered) != 3:
        raise ValueError("native baseline service coverage missing")
    services = []
    for n, (state, plan, receipt) in enumerate(zip(states, plans, receipts, strict=True)):
        if (
            state[0] != clock["script_tick"]
            or state[1] != clock["economy_date"]
            or delivered[n] not in (0, None)
        ):
            raise ValueError("native ready baseline is not coherent")
        service = dict(
            service=n,
            plan=plan.digest,
            vehicle=receipt["vehicle"],
            snapshot=state,
            delivered=delivered[n],
            revenue=None,
            operating_costs=None,
            completed_delivery_cycles=None,
            profit_this_year=state[20],
            profit_last_year=None,
            running_cost_rate_per_year=None,
            station_waiting_cargo=state[15],
            cargo_load=state[11],
            capacity=state[7],
        )
        services.append(_service_value(service, plan, receipt))
    return dict(
        **clock,
        sequence=0,
        annual_targets=value["annual_targets"],
        elapsed_economy_days=0,
        wall_elapsed_seconds=wall_elapsed_seconds,
        services=services,
        finance=value,
        source_digests=[],
    )


def telemetry_options(metadata, receipts):
    from app.simulation.openttd.freight_telemetry import validate_bindings

    options = metadata.get("capacity_telemetry")
    if options is None:
        return None
    if options.get("version") == 2:
        if set(options) != {"version", "vehicle_count", "max_tick_gap"}:
            raise ValueError("unsupported capacity telemetry options")
        bindings = [dict(service=n, vehicle=r["vehicle"]) for n, r in enumerate(receipts)]
        for n, receipt in enumerate(receipts):
            for extra in receipt.get("additional_vehicles", []):
                if extra["service"] != n:
                    raise ValueError("additional vehicle service binding mismatch")
                bindings.append(dict(service=n, vehicle=extra["vehicle"]))
        if len(bindings) != options["vehicle_count"]:
            raise ValueError("capacity telemetry physical fleet count mismatch")
        bindings = validate_bindings(bindings)
    elif options.get("version") == 1 and set(options) == {"version", "bindings", "max_tick_gap"}:
        bindings = validate_bindings(options["bindings"])
    else:
        raise ValueError("unsupported capacity telemetry options")
    if any(dict(service=n, vehicle=r["vehicle"]) not in bindings for n, r in enumerate(receipts)):
        raise ValueError("telemetry original fleet binding changed")
    from app.simulation.openttd.freight_telemetry import SampleWindow

    SampleWindow(options["max_tick_gap"])
    return options | dict(bindings=bindings)


def validate_telemetry_snapshot(samples, plans, clock):
    for sample in samples:
        plan = plans[sample["service"]]
        if (
            sample["capacity"] != plan.f[5]
            or sample["source_tile"] != plan.a[4]
            or sample["destination_tile"] != plan.a[6]
            or not clock["economy_date"] <= sample["economy_date"] <= clock["economy_date"] + 2
            or sample["tick"] < clock["script_tick"]
        ):
            raise ValueError("telemetry plan or snapshot clock mismatch")


async def collect_telemetry(session, directory, options, sequence, result, budgets, windows):
    from app.simulation.openttd.freight_telemetry import TelemetryReadback, TelemetryRequest
    from app.simulation.openttd.proof.freight_delivery import exchange

    samples = []
    digests = []
    for binding in options["bindings"]:
        if result["requests"] >= budgets["requests"]:
            raise ValueError("continuous request budget exhausted")
        name = f"continuous-t{sequence}-v{binding['vehicle']}"
        result["requests"] += 1
        sample = await exchange(
            session, TelemetryRequest(name, **binding), directory, response_type=TelemetryReadback
        )
        windows[sample.vehicle].append(sample)
        samples.append(sample.model_dump(mode="json"))
        digests.append(sha256(directory / f"{name}-response.json"))
    _durable_append(
        directory / "continuous-telemetry.jsonl", dict(sequence=sequence, samples=samples)
    )
    return samples, digests


async def monitor_network(prepared, session, plans, receipts, metadata, result):
    from app.simulation.openttd.freight_finance import ContinuousReadback, ContinuousRequest
    from app.simulation.openttd.proof.freight_delivery import exchange

    started = time.monotonic()
    last_progress = started
    directory = prepared.directory
    snapshots = []
    movement = {}
    progress = None
    telemetry = telemetry_options(metadata, receipts)
    from app.simulation.openttd.freight_telemetry import SampleWindow

    windows = (
        {
            b["vehicle"]: SampleWindow(telemetry["max_tick_gap"], MAX_POLLS + 1)
            for b in telemetry["bindings"]
        }
        if telemetry
        else {}
    )
    original_observer = session._frame_observer
    frame_bytes = 0
    frame_count = 0

    def bounded_observer(direction, frame):
        nonlocal frame_bytes, frame_count
        frame_bytes += len(frame)
        frame_count += 1
        if (
            frame_bytes > metadata["budgets"]["monitor_frame_bytes"]
            or frame_count > metadata["budgets"]["monitor_frames"]
        ):
            raise ValueError("continuous secure frame budget exhausted")
        if original_observer is not None:
            original_observer(direction, frame)

    async def query(kind, name, service=-1):
        if result["requests"] >= metadata["budgets"]["requests"]:
            raise ValueError("continuous request budget exhausted")
        result["requests"] += 1
        return await exchange(
            session,
            ContinuousRequest(type=kind, request_id=name, service=service),
            directory,
            response_type=ContinuousReadback,
        )

    session._frame_observer = bounded_observer
    try:
        async with asyncio.timeout(MONITOR_SECONDS):
            begin = await query("continuous-begin", "continuous-begin")
            baseline = _baseline_snapshot(begin, plans, receipts, time.monotonic() - started)
            baseline["source_digests"] = [sha256(directory / "continuous-begin-response.json")]
            if telemetry:
                samples, digests = await collect_telemetry(
                    session, directory, telemetry, 0, result, metadata["budgets"], windows
                )
                validate_telemetry_snapshot(samples, plans, baseline)
                baseline["vehicle_telemetry"] = samples
                baseline["source_digests"].extend(digests)
            snapshots.append(baseline)
            progress = EconomyProgress(baseline, baseline["annual_targets"])
            previous_date = baseline["economy_date"]
            _durable_append(directory / "continuous-snapshots.jsonl", baseline)
            for sequence in range(1, MAX_POLLS + 1):
                await asyncio.sleep(POLL_SECONDS)
                _resource_check(directory, prepared.spec.workspace.logs, frame_bytes)
                company = await query("continuous-company", f"continuous-{sequence}-company")
                finance = company.model_dump(mode="json")
                clock = finance["clock"]
                services = []
                digests = [sha256(directory / f"continuous-{sequence}-company-response.json")]
                for n, plan in enumerate(plans):
                    read = await query("continuous-service", f"continuous-{sequence}-s{n}", n)
                    if (
                        not clock["economy_date"]
                        <= read.clock.economy_date
                        <= clock["economy_date"] + 2
                    ):
                        raise ValueError("continuous snapshot economy coherence exceeded")
                    service_value = _service_value(read, plan, receipts[n])
                    signature = (
                        service_value["snapshot"][8],
                        service_value["cargo_load"],
                        service_value["delivered"],
                    )
                    prior = movement.get(n)
                    if prior is None or signature != prior[0]:
                        movement[n] = (signature, time.monotonic())
                    elif (
                        time.monotonic() - prior[1]
                        > metadata["budgets"]["monitor_vehicle_stall_seconds"]
                    ):
                        raise ValueError("continuous vehicle movement/cargo stalled")
                    services.append(service_value)
                    digests.append(sha256(directory / f"continuous-{sequence}-s{n}-response.json"))
                if clock["economy_date"] != previous_date:
                    last_progress = time.monotonic()
                    previous_date = clock["economy_date"]
                if time.monotonic() - last_progress > metadata["budgets"]["monitor_stall_seconds"]:
                    raise ValueError("native economy simulation stalled")
                flags = progress.observe(clock)
                snapshot = dict(
                    **clock,
                    sequence=sequence,
                    annual_targets=baseline["annual_targets"],
                    elapsed_economy_days=clock["economy_date"] - baseline["economy_date"],
                    wall_elapsed_seconds=time.monotonic() - started,
                    services=services,
                    finance=finance,
                    source_digests=digests,
                )
                if telemetry:
                    samples, telemetry_digests = await collect_telemetry(
                        session,
                        directory,
                        telemetry,
                        sequence,
                        result,
                        metadata["budgets"],
                        windows,
                    )
                    validate_telemetry_snapshot(samples, plans, snapshot)
                    snapshot["vehicle_telemetry"] = samples
                    digests.extend(telemetry_digests)
                snapshots.append(snapshot)
                _durable_append(directory / "continuous-snapshots.jsonl", snapshot)
                for kind in ("monthly", "quarterly", "annual"):
                    if flags[kind]:
                        write_json(directory / f"continuous-{kind}-{sequence}.json", snapshot)
                if progress.annual_count == 5:
                    if telemetry:
                        _resource_check(directory, prepared.spec.workspace.logs, frame_bytes)
                    receipt = continuous_summary(snapshots, receipts)
                    write_json(directory / "continuous-summary.json", receipt)
                    return receipt
            raise ValueError("finite continuous polling budget exhausted")
    finally:
        session._frame_observer = original_observer
        if telemetry:
            write_json(
                directory / "continuous-telemetry-summary.json",
                {str(vehicle): window.report() for vehicle, window in windows.items()},
            )
        if snapshots:
            write_json(directory / "continuous-periods.json", period_reports(snapshots))
        write_json(
            directory / "continuous-partial.json",
            dict(
                snapshots=len(snapshots),
                complete=progress is not None and progress.annual_count == 5,
                completed_years=progress.annual_count if progress is not None else 0,
                automatic_resume=False,
            ),
        )


def continuous_summary(snapshots, receipts):
    from app.simulation.openttd.freight_finance import reconcile_snapshots

    reports = period_reports(snapshots)
    if not reports["complete"]:
        raise ValueError("five complete native economy years not observed")
    return dict(
        classification="NATIVE_FIVE_YEAR_CONTINUOUS",
        complete_economy_years=5,
        elapsed_economy_days=snapshots[-1]["elapsed_economy_days"],
        service_count=3,
        services=receipts,
        infrastructure_and_vehicle_capex_gbp=sum(
            r["construction_purchase_spending"]
            + sum(v["purchase_capex"] for v in r.get("additional_vehicles", []))
            for r in receipts
        ),
        financial_metrics=reconcile_snapshots(snapshots),
        observation_counts={k: len(reports[k]) for k in ("monthly", "quarterly", "annual")},
        snapshots_sha256=None,
    )


def verify_continuous_evidence(directory: Path, *, _full=True, recovery_directory=None):
    """Replay retained raw native readbacks; partial journals remain inspectable."""
    from app.simulation.openttd.freight_delivery import DeliveryPlan
    from app.simulation.openttd.freight_finance import ContinuousReadback, ContinuousRequest

    directory = Path(directory)
    _resource_check(directory, directory)
    begin_q = ContinuousRequest(type="continuous-begin", request_id="continuous-begin", service=-1)
    begin = ContinuousReadback.parse_for(
        begin_q, (directory / "continuous-begin-response.json").read_bytes()
    )
    if begin_q.to_bytes() != (directory / "continuous-begin-request.json").read_bytes():
        raise ValueError("continuous begin request changed")
    targets = begin.model_dump(mode="json")["annual_targets"]
    snapshots = [
        json.loads(line)
        for line in (directory / "continuous-snapshots.jsonl").read_text().splitlines()
    ]
    if not 1 <= len(snapshots) <= MAX_POLLS + 1:
        raise ValueError("continuous snapshot count outside sealed budget")
    progress = EconomyProgress(begin.model_dump(mode="json")["clock"], targets)
    plans = [
        DeliveryPlan.model_validate_json((directory / f"native-plan-{n}.json").read_bytes())
        for n in range(3)
    ]
    receipts = [
        json.loads((directory / f"service-receipt-{n}.json").read_bytes()) for n in range(3)
    ]
    metadata_path = directory / "PRELAUNCH.json"
    metadata = json.loads(metadata_path.read_bytes()) if metadata_path.exists() else {}
    if metadata.get("capacity_intervention") is not None:
        from app.simulation.openttd.freight_native_network import replay_capacity_intervention

        receipts = replay_capacity_intervention(directory, plans, receipts, metadata)
    telemetry = telemetry_options(metadata, receipts)
    from app.simulation.openttd.freight_telemetry import (
        SampleWindow,
        decode_telemetry,
        telemetry_request,
    )

    windows = (
        {
            b["vehicle"]: SampleWindow(telemetry["max_tick_gap"], MAX_POLLS + 1)
            for b in telemetry["bindings"]
        }
        if telemetry
        else {}
    )
    telemetry_journal = []
    wire_expected = ["continuous-begin"]

    def replay_telemetry(sequence, expected):
        samples = []
        for binding in telemetry["bindings"]:
            name = f"continuous-t{sequence}-v{binding['vehicle']}"
            request = telemetry_request(name, **binding)
            if request != (directory / f"{name}-request.json").read_bytes():
                raise ValueError("telemetry request identity changed")
            response = directory / f"{name}-response.json"
            sample = decode_telemetry(response.read_bytes(), request)
            windows[sample.vehicle].append(sample)
            samples.append(sample.model_dump(mode="json"))
            expected["source_digests"].append(sha256(response))
            wire_expected.append(name)
        validate_telemetry_snapshot(samples, plans, expected)
        expected["vehicle_telemetry"] = samples
        telemetry_journal.append(dict(sequence=sequence, samples=samples))

    baseline = _baseline_snapshot(begin, plans, receipts, snapshots[0]["wall_elapsed_seconds"])
    baseline["source_digests"] = [sha256(directory / "continuous-begin-response.json")]
    if telemetry:
        replay_telemetry(0, baseline)
    if baseline != snapshots[0]:
        raise ValueError("continuous ready baseline replay mismatch")
    for sequence, snapshot in enumerate(snapshots[1:], start=1):
        values = []
        digests = []
        for service in [-1, 0, 1, 2]:
            kind = "company" if service == -1 else f"s{service}"
            name = f"continuous-{sequence}-{kind}"
            q = ContinuousRequest(
                type="continuous-company" if service == -1 else "continuous-service",
                request_id=name,
                service=service,
            )
            wire_expected.append(name)
            if q.to_bytes() != (directory / f"{name}-request.json").read_bytes():
                raise ValueError("continuous request identity changed")
            response = directory / f"{name}-response.json"
            values.append(ContinuousReadback.parse_for(q, response.read_bytes()))
            digests.append(sha256(response))
        company = values[0].model_dump(mode="json")
        clock = company["clock"]
        expected_services = [
            _service_value(read, plans[n], receipts[n]) for n, read in enumerate(values[1:])
        ]
        for read in values[1:]:
            if not clock["economy_date"] <= read.clock.economy_date <= clock["economy_date"] + 2:
                raise ValueError("continuous readback coherence exceeded")
        expected = dict(
            **clock,
            sequence=sequence,
            annual_targets=targets,
            elapsed_economy_days=clock["economy_date"] - begin.clock.economy_date,
            wall_elapsed_seconds=snapshot["wall_elapsed_seconds"],
            services=expected_services,
            finance=company,
            source_digests=digests,
        )
        if telemetry:
            replay_telemetry(sequence, expected)
        if (
            snapshot != expected
            or snapshot["wall_elapsed_seconds"] < 0
            or snapshot["wall_elapsed_seconds"] > MONITOR_SECONDS
        ):
            raise ValueError("continuous snapshot differs from raw native evidence")
        if (
            sequence
            and snapshot["wall_elapsed_seconds"] < snapshots[sequence - 1]["wall_elapsed_seconds"]
        ):
            raise ValueError("continuous wall clock regressed")
        progress.observe(clock)
    if telemetry:
        if telemetry_journal != [
            json.loads(line)
            for line in (directory / "continuous-telemetry.jsonl").read_text().splitlines()
        ]:
            raise ValueError("telemetry durable journal replay mismatch")
        if {str(vehicle): window.report() for vehicle, window in windows.items()} != json.loads(
            (directory / "continuous-telemetry-summary.json").read_bytes()
        ):
            raise ValueError("telemetry summary replay mismatch")
    _verify_continuous_wire(
        directory, wire_expected, complete=progress.annual_count == 5, telemetry=telemetry
    )
    reports = period_reports(snapshots)
    for kind in ("monthly", "quarterly", "annual"):
        for snapshot in reports[kind]:
            if snapshot != json.loads(
                (directory / f"continuous-{kind}-{snapshot['sequence']}.json").read_bytes()
            ):
                raise ValueError("continuous durable period differs from raw evidence")
    if reports != json.loads((directory / "continuous-periods.json").read_bytes()):
        raise ValueError("continuous periodic report replay mismatch")
    summary = continuous_summary(snapshots, receipts) if reports["complete"] else None
    if summary is not None and summary != json.loads(
        (directory / "continuous-summary.json").read_bytes()
    ):
        raise ValueError("continuous summary replay mismatch")
    capex = None
    if _full:
        from app.simulation.openttd.freight_native_network import verify_network_receipt

        network_receipt = verify_network_receipt(
            directory,
            allow_continuous_partial=not reports["complete"],
            recovery_directory=recovery_directory,
        )
        capex = network_receipt["infrastructure_and_vehicle_capex_gbp"]
    output = dict(
        snapshots=snapshots, **reports, summary=summary, infrastructure_and_vehicle_capex_gbp=capex
    )
    if recovery_directory is not None:
        output["offline_recovery"] = verify_recovery_metadata(directory, recovery_directory)
    return output


def verify_continuous_network(
    directory,
    metadata,
    network,
    plan,
    services,
    links,
    seal,
    cleanup,
    *,
    allow_partial=False,
    recovery=None,
):
    """Reuse qualified planner/source replay, verify construction and complete monitor."""
    from app.planning.canonical import plan_hash
    from app.simulation.openttd.freight_delivery import DeliveryPlan, admit, verify_snapshot
    from app.simulation.openttd.freight_native_network import (
        network_route_readback,
        service_construction,
        shared_stages,
        verified_exchanges,
    )
    from app.simulation.openttd.proof.endpoints import verify_retained_endpoints

    records, wire_ids = verified_exchanges(directory, allow_continuous_partial=allow_partial)
    expected_ids = [f"select-{n}" for n in range(3)]
    bindings = []
    receipts = []
    plans = [
        DeliveryPlan.model_validate_json((directory / f"native-plan-{n}.json").read_bytes())
        for n in range(3)
    ]
    for n, (route_id, service) in enumerate(services):
        selection = service.selection_request(request_id=f"select-{n}")
        if selection.to_bytes() != (directory / f"select-{n}-request.json").read_bytes():
            raise ValueError("continuous selected service changed")
        native = admit(
            records[f"select-{n}"],
            seal,
            links.post_qualification_save_digest,
            None,
            executor_source=metadata["predecessor"]["executor_source_digest"],
            selection_digest=plan_hash(plan),
        )
        if native != plans[n]:
            raise ValueError("continuous native plan changed")
        binding = service.validate_native_selection(native, records[f"select-{n}"])
        bindings.append(binding)
        expected_ids.extend(
            [f"activate-{n}"]
            + [name for i in range(10) for name in (f"s{n}-build-{i}", f"s{n}-read-{i}")]
        )
        activation = records[f"activate-{n}"]
        verify_snapshot(native, activation)
        if activation.status != "READ" or activation.s[22] != 0 or activation.s[4] != -1:
            raise ValueError("continuous activation mismatch")
        local = {"inspect-1": activation}
        for i in range(10):
            for op in ("build", "read"):
                local[f"{op}-{i}"] = records[f"s{n}-{op}-{i}"]
        receipt = dict(vehicle=local["read-9"].s[4])
        receipt.update(
            service_construction(
                native,
                local,
                reused_stages=shared_stages(plan, services, n),
                log_path=directory / "stderr.log",
                network_plans=tuple(p.digest for p in plans),
            )
        )
        receipt.update(network_route_readback(directory / "stderr.log", native, service))
        receipt.update(route_id=route_id, planning_binding=binding)
        if receipt != json.loads((directory / f"service-receipt-{n}.json").read_bytes()):
            raise ValueError("continuous construction receipt mismatch")
        receipts.append(receipt)
    if (
        wire_ids != expected_ids
        or set(records) != set(expected_ids)
        or bindings != json.loads((directory / "network-bindings.json").read_bytes())
    ):
        raise ValueError("continuous construction sequence changed")
    if metadata.get("capacity_intervention") is not None:
        from app.simulation.openttd.freight_native_network import replay_capacity_intervention

        receipts = replay_capacity_intervention(directory, plans, receipts, metadata)
    intervention_requests = 2 if metadata.get("capacity_intervention") is not None else 0
    intervention_mutations = 4 if intervention_requests else 0
    telemetry = telemetry_options(metadata, receipts)
    telemetry_count = len(telemetry["bindings"]) if telemetry else 0
    verified = verify_continuous_evidence(directory, _full=False)
    complete = verified["complete"]
    if not complete and not allow_partial:
        raise ValueError("continuous observation incomplete")
    result = json.loads((directory / "result.json").read_bytes())
    if complete:
        aggregate = verified["summary"] | dict(
            before_save_sha256=sha256(directory / "before.sav"),
            qualified_save_sha256=sha256(directory / "qualified.sav"),
            after_save_sha256=sha256(directory / "after.sav"),
        )
        if aggregate != json.loads((directory / "receipt.json").read_bytes()):
            raise ValueError("continuous receipt mismatch")
        if (
            result["launches"],
            result["connections"],
            result["mutations"],
            result["requests"],
            result["status"],
        ) != (
            1,
            1,
            30 + intervention_mutations,
            67
            + 4 * (len(verified["snapshots"]) - 1)
            + telemetry_count * len(verified["snapshots"])
            + intervention_requests,
            "FAILED" if recovery is not None else "NATIVE_FIVE_YEAR_CONTINUOUS_VERIFIED",
        ):
            raise ValueError("continuous one-session accounting mismatch")
    else:
        if (
            (result["launches"], result["connections"], result["mutations"])
            != (1, 1, 30 + intervention_mutations)
            or not 67 <= result["requests"] <= metadata["budgets"]["requests"]
            or result["status"] != "FAILED"
        ):
            raise ValueError("continuous interrupted-session accounting mismatch")
        aggregate = dict(
            classification="PARTIAL_NATIVE_CONTINUOUS_OBSERVATION",
            infrastructure_and_vehicle_capex_gbp=sum(
                r["construction_purchase_spending"]
                + sum(v["purchase_capex"] for v in r.get("additional_vehicles", []))
                for r in receipts
            ),
            complete=False,
        )
    if (
        not cleanup.get("reaped")
        or not cleanup.get("workspace_disposed")
        or not cleanup.get("credential_removed")
        or cleanup.get("cleanup_error")
        or cleanup.get("verification_error")
    ):
        raise ValueError("continuous cleanup incomplete")
    if metadata.get("scenario") and (
        result.get("funding_requests"),
        result.get("funding_mutations"),
    ) != (2, 1):
        raise ValueError("continuous funding accounting mismatch")
    logs = (directory / "stdout.log").read_text() + (directory / "stderr.log").read_text()
    for name in (
        ("before", "qualified", "after") if complete else ("before", "qualified", "failure")
    ):
        if logs.count("Map successfully saved to '" + str(directory / (name + ".sav"))) != 1:
            raise ValueError("continuous unique native save completion missing")
    verify_retained_endpoints(
        cleanup["endpoint_verification"],
        metadata | {"endpoints": [metadata["game_port"], metadata["admin_port"]]},
    )
    return aggregate


def _verify_continuous_wire(directory, expected_ids, *, complete, telemetry=None):
    from app.simulation.openttd.admin_protocol import AdminFrameDecoder
    from app.simulation.openttd.gamescript_transport import (
        ADMIN_GAMESCRIPT,
        SERVER_GAMESCRIPT,
        decode_gamescript,
        encode_gamescript,
    )

    frames = json.loads((directory / "frames.json").read_bytes())
    sent = [bytes.fromhex(frame) for direction, frame in frames if direction == "outbound"]
    replies = []
    decoder = AdminFrameDecoder()
    for direction, frame in frames:
        if direction == "inbound":
            replies.extend(
                decode_network_response(body)
                for kind, body in decoder.feed_frames(bytes.fromhex(frame))
                if kind == SERVER_GAMESCRIPT
            )
    wire_ids = []
    for frame in sent:
        if len(frame) > 2 and frame[2] == ADMIN_GAMESCRIPT:
            value = json.loads(decode_gamescript(frame[3:]))
            if str(value.get("type", "")).startswith("continuous-"):
                wire_ids.append(value["request_id"])
    if wire_ids[: len(expected_ids)] != expected_ids:
        raise ValueError("continuous secure request order mismatch")
    # A partial next snapshot may have up to four completed/failed exchanges.
    extra = wire_ids[len(expected_ids) :]
    width = 4 + (len(telemetry["bindings"]) if telemetry else 0)
    initial = 1 + (len(telemetry["bindings"]) if telemetry else 0)
    next_sequence = (len(expected_ids) - initial) // width + 1
    permitted = [f"continuous-{next_sequence}-{part}" for part in ("company", "s0", "s1", "s2")]
    if telemetry:
        permitted += [f"continuous-t{next_sequence}-v{b['vehicle']}" for b in telemetry["bindings"]]
    if (complete and extra) or extra != permitted[: len(extra)] or len(extra) > width:
        raise ValueError("unexpected continuous exchanges after verified prefix")
    for name in expected_ids:
        request = (directory / f"{name}-request.json").read_bytes()
        response = (directory / f"{name}-response.json").read_bytes()
        if sent.count(encode_gamescript(request)) != 1 or replies.count(response) != 1:
            raise ValueError("continuous unique secure exchange missing")


def decode_continuous_response(payload):
    """Native GSAdmin.Send limit is 1450; preserve the legacy application decoder."""
    if not payload.endswith(b"\0") or b"\0" in payload[:-1] or not 0 < len(payload) - 1 <= 1450:
        raise ValueError("invalid bounded continuous GameScript payload")
    raw = payload[:-1]
    value = json.loads(raw)
    if not isinstance(value, dict) or not str(value.get("type", "")).startswith("continuous-"):
        raise ValueError("typed continuous native response required")
    return raw


def decode_network_response(payload):
    from app.simulation.openttd.gamescript_transport import decode_gamescript
    from app.simulation.openttd.observation_protocol import MAX_PAYLOAD_BYTES

    if len(payload) > MAX_PAYLOAD_BYTES + 1:
        import json

        from app.simulation.openttd.freight_capacity_execution import decode_capacity_wire

        if payload.endswith(b"\0") and json.loads(payload[:-1]).get("type") in (
            "capacity-add-result",
            "capacity-read-result",
        ):
            return decode_capacity_wire(payload)
        return decode_continuous_response(payload)
    return decode_gamescript(payload)


def _recovery_metadata(directory):
    """Derive final policy correspondence only; all observations remain native originals."""
    import hashlib
    import zipfile

    from app.simulation.openttd.proof.harness import manifest
    from app.simulation.openttd.scenario_capital import company_policy_provenance

    directory = Path(directory).resolve()
    if manifest(directory) != (directory / "artifact-manifest.sha256").read_text():
        raise ValueError("recovery original artifact manifest mismatch")
    metadata = json.loads((directory / "PRELAUNCH.json").read_bytes())
    if sha256(directory / "PRELAUNCH.json") != (directory / "PRELAUNCH.sha256").read_text().strip():
        raise ValueError("recovery original prelaunch mismatch")
    result = json.loads((directory / "result.json").read_bytes())
    expected_error = (
        "FileExistsError: [Errno 17] File exists: '" + str(directory / "company-policy.json") + "'"
    )
    if (
        result.get("status") != "FAILED"
        or result.get("error") != expected_error
        or metadata.get("company_policy_provenance_version", 1) != 1
        or metadata.get("continuous_years") != 5
    ):
        raise ValueError("recovery requires exact immutable-policy finalization failure")
    archive_path = directory / "frozen-source.zip"
    if sha256(archive_path) != metadata["predecessor"]["executor_source_digest"]:
        raise ValueError("recovery original source archive mismatch")
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("recovery duplicate source archive member")
        for name in names:
            path = Path(name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("recovery unsafe source archive member")
            digest = hashlib.sha256(archive.read(name)).hexdigest()
            if name.startswith("staged/"):
                staged = name.removeprefix("staged/")
                base = Path(metadata["workspace"])
                original = (
                    base / staged
                    if staged == "openttd.cfg"
                    else base / "game/RoadFreightProof" / staged
                )
            else:
                original = Path(__file__).resolve().parents[3] / name
            if digest != metadata["frozen"].get(str(original)):
                raise ValueError("recovery frozen source member mismatch")
    financing = json.loads((directory / "scenario-capital.json").read_bytes())
    if json.loads((directory / "company-policy.json").read_bytes()) != company_policy_provenance(
        directory, financing
    ):
        raise ValueError("recovery initial company policy mismatch")
    return dict(
        schema="derived-offline-continuous-finalization-v1",
        classification="DERIVED_METADATA_ONLY",
        original_directory=str(directory),
        original_manifest_sha256=sha256(directory / "artifact-manifest.sha256"),
        original_prelaunch_sha256=sha256(directory / "PRELAUNCH.json"),
        original_result_sha256=sha256(directory / "result.json"),
        original_terminal=result,
        company_policy_final=company_policy_provenance(directory, financing, complete=True),
        limitations=["Historical terminal remains FAILED", "No native reload performed"],
    )


def verify_recovery_metadata(directory, recovery_directory):
    recovery_directory = Path(recovery_directory).resolve()
    directory = Path(directory).resolve()
    if recovery_directory == directory or directory in recovery_directory.parents:
        raise ValueError("recovery must be separate from original evidence")
    path = recovery_directory / "derived-finalization.json"
    if sha256(path) != (recovery_directory / "derived-finalization.sha256").read_text().strip():
        raise ValueError("derived finalization integrity mismatch")
    recovered = json.loads(path.read_bytes())
    if recovered != _recovery_metadata(directory):
        raise ValueError("derived finalization differs from original evidence")
    return recovered


def recover_continuous_evidence(directory, recovery_directory):
    """Write new immutable derived metadata and run the existing complete offline replay."""
    recovery_directory = Path(recovery_directory).resolve()
    directory = Path(directory).resolve()
    if recovery_directory == directory or directory in recovery_directory.parents:
        raise ValueError("recovery must be separate from original evidence")
    recovered = _recovery_metadata(directory)
    recovery_directory.mkdir(parents=True, exist_ok=False)
    write_json(recovery_directory / "derived-finalization.json", recovered)
    with (recovery_directory / "derived-finalization.sha256").open("x") as handle:
        handle.write(sha256(recovery_directory / "derived-finalization.json") + "\n")
    return verify_continuous_evidence(directory, recovery_directory=recovery_directory)
