"""Offline, explicit fleet-allocation comparisons; no native execution authority."""

import json
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from app.planning.canonical import plan_hash, scenario_hash
from app.planning.domain import ExecutionPlan, PlanningScenario
from app.planning.optimizer import OptimizerFailure, optimize_candidate_network
from app.planning.validation import validate_execution_plan


def compare_capacity_allocations(
    scenario: PlanningScenario, service_demands: dict[str, str]
) -> list[dict]:
    """Force the original services and one explicit extra vehicle, without extra demand."""
    if set(service_demands) != {"S1", "S2", "S3"} or len(set(service_demands.values())) != 3:
        raise ValueError("three distinct original service mappings required")
    if set(service_demands.values()) != {d.demand_id for d in scenario.cargo_demands}:
        raise ValueError("service mappings must cover original demands exactly")
    if scenario.constraints.network_selection is None:
        raise ValueError("P08 network selection required")
    rows = []
    for name, target in (("A", None), ("B", "S2"), ("C", "S3")):
        value = scenario.model_dump(mode="json")
        counts = {d: 1 + (service == target) for service, d in service_demands.items()}
        value["constraints"]["network_selection"].update(
            minimum_vehicles_by_demand=counts, max_vehicles=sum(counts.values())
        )
        variant = PlanningScenario.model_validate_json(json.dumps(value))
        row = dict(
            configuration=name,
            extra_vehicle_service=target,
            scenario=variant.model_dump(mode="json"),
            scenario_digest=scenario_hash(variant),
        )
        try:
            result = optimize_candidate_network(variant)
            validate_execution_plan(result.plan, variant)
        except OptimizerFailure as exc:
            row.update(feasible=False, failure_code=exc.code.value)
        else:
            allocation = {d: g.count for g in result.plan.fleet.groups for d in g.demand_ids}
            if allocation != counts:
                raise ValueError("comparison did not preserve exact requested vehicle allocation")
            infrastructure = sum(
                (a.estimated_build_cost_gbp for a in result.plan.infrastructure.actions), Decimal(0)
            )
            purchase = result.metrics.vehicle_purchase_cost_gbp
            assert purchase is not None
            row.update(
                feasible=True,
                independently_validated=True,
                allocation={s: allocation[d] for s, d in service_demands.items()},
                plan=result.plan.model_dump(mode="json"),
                plan_digest=plan_hash(result.plan),
                estimated_vehicle_purchase_gbp=str(purchase),
                estimated_infrastructure_gbp=str(infrastructure),
                estimated_capex_gbp=str(infrastructure + purchase),
            )
        rows.append(row)
    return rows


def observed_capacity_baseline(p07: dict) -> dict:
    """Retain observed totals; never substitute Attempt 19 constants for evidence."""
    total = next(t for t in p07["totals"] if t["scope"] == "network")
    return {
        "economy_days": p07["lifecycle"]["elapsed_economy_days"],
        "cargo": total["delivered_cargo"],
        "network_revenue_gbp": total["revenue"],
        "observed_capex_gbp": p07["finance"]["capex"],
    }


def prepare_capacity_experiment(attempt: Path, p07: dict) -> dict:
    """Bind a preparation-only comparison to retained evidence and existing P07 replay."""
    attempt = attempt.resolve()
    from app.simulation.openttd.freight_matched_state import inspect_capacity_source

    matched_source = inspect_capacity_source(attempt)
    if Path(p07["source_directory"]).resolve() != attempt:
        raise ValueError("P07 source directory differs from retained attempt")
    if p07.get("classification") != "OFFLINE_RECOVERED_REPLAY_VERIFIED_CONTINUOUS_OBSERVATIONS":
        raise ValueError("offline recovered verified P07 evidence required")
    files = (
        "planning-scenario.json",
        "execution-plan.json",
        "receipt.json",
        "frozen-source.zip",
        "continuous-snapshots.jsonl",
        "result.json",
        "service-receipt-0.json",
        "service-receipt-1.json",
        "service-receipt-2.json",
    )
    digests = {name: sha256((attempt / name).read_bytes()).hexdigest() for name in files}
    scenario = PlanningScenario.model_validate_json((attempt / files[0]).read_bytes())
    plan = ExecutionPlan.model_validate_json((attempt / files[1]).read_bytes())
    validate_execution_plan(plan, scenario)
    routes = {r.route_id: r for r in plan.routes}
    services = p07["snapshots"][0]["services"]
    mapping = {}
    for index, service in enumerate(services, 1):
        assignments = routes[service["route_id"]].cargo_assignments
        if len(assignments) != 1:
            raise ValueError("one original demand per service required")
        mapping[f"S{index}"] = assignments[0].demand_id
    rows = compare_capacity_allocations(scenario, mapping)
    receipt = json.loads((attempt / "receipt.json").read_bytes())
    if (
        receipt["snapshots_sha256"] is not None
        and receipt["snapshots_sha256"] != digests["continuous-snapshots.jsonl"]
    ):
        raise ValueError("retained receipt/snapshot hash mismatch")
    if not all(row["feasible"] for row in rows):
        raise ValueError("all three controlled allocations must be feasible")
    baseline_plan = rows[0]["plan"]
    for row in rows:
        for key in ("routes", "infrastructure"):
            if (
                row["plan"][key] != baseline_plan[key]
                or baseline_plan[key] != plan.model_dump(mode="json")[key]
            ):
                raise ValueError("allocation comparison changes original routes or infrastructure")
    original_groups = {
        g.fleet_group_id: g.model_dump(mode="json", exclude={"count"}) for g in plan.fleet.groups
    }
    for row in rows:
        actual_groups = {
            g["fleet_group_id"]: {k: v for k, v in g.items() if k != "count"}
            for g in row["plan"]["fleet"]["groups"]
        }
        if actual_groups != original_groups:
            raise ValueError("allocation comparison changes original fleet semantics")
    monthly = []
    snapshots = {str(s["sequence"]): s for s in p07["snapshots"]}
    for service in services:
        periods = [
            p
            for p in p07["periods"]
            if p["period"] == "monthly" and p["scope"] == service["route_id"]
        ]
        queues = [
            next(
                s
                for s in snapshots[p["evidence_refs"][-1]]["services"]
                if s["route_id"] == service["route_id"]
            )["station_waiting"]
            for p in periods
        ]
        monthly.append(
            dict(
                service=f"S{len(monthly) + 1}",
                monthly_endpoint_samples=len(queues),
                mean_sampled_queue=sum(queues) / len(queues) if queues else None,
            )
        )
    candidates = [
        q for q in monthly if q["service"] in ("S2", "S3") and q["mean_sampled_queue"] is not None
    ]
    preferred = (
        max(candidates, key=lambda q: q["mean_sampled_queue"])["service"]
        if len(candidates) == 2
        and candidates[0]["mean_sampled_queue"] != candidates[1]["mean_sampled_queue"]
        else None
    )
    historical_status = json.loads((attempt / "result.json").read_bytes())["status"]
    if historical_status != "FAILED":
        raise ValueError(
            "this experiment requires retained FAILED baseline plus offline verification"
        )
    purchases = []
    for index in range(3):
        service_receipt = json.loads((attempt / f"service-receipt-{index}.json").read_bytes())
        if service_receipt["planning_binding"]["selection"]["a"][3] != 123:
            raise ValueError("this experiment requires observed engine123")
        purchases.append(service_receipt["mutation_costs"][6])
    if len(set(purchases)) != 1:
        raise ValueError("homogeneous observed purchase prices required")
    rates = {
        s["running_cost_rate_per_year"]
        for snap in p07["snapshots"]
        for s in snap["services"]
        if s["running_cost_rate_per_year"] is not None
    }
    if len(rates) != 1 or any(s["capacity"] != 20 for s in services):
        raise ValueError("homogeneous observed twenty-unit fleet and running-cost rate required")
    return dict(
        classification="CONTROLLED_CAPACITY_EXPERIMENT_PREPARATION",
        native_launches=0,
        admin_connections=0,
        historical_attempt_status=historical_status,
        input_sha256=digests,
        baseline_scenario_digest=scenario_hash(scenario),
        service_demands=mapping,
        monthly_queue_samples=monthly,
        configurations=rows,
        recommended_service=preferred,
        recommendation_basis=(
            "Higher sampled monthly source queue; a test priority, not proven marginal benefit."
        ),
        baseline=observed_capacity_baseline(p07),
        expected_incremental_vehicle_purchase_gbp=str(purchases[0]),
        purchase_classification="Observed historical engine price; future command quote required.",
        annual_running_cost_rate_gbp=str(next(iter(rates))),
        actual_incremental_operating_expenses_gbp=None,
        operating_profit_gbp=None,
        roi=None,
        equivalence_requirements=[
            "Same qualified initial save and world/cargo; identical newly staged "
            "telemetry-enabled bridge bytes across A/B/C. Preserve the original "
            "archive unchanged as historical evidence.",
            "Same original route geometry, order flags, engine and vehicle settings; "
            "verify a common dispatch date/state after paused arm-specific purchases.",
            "Same 1826-economy-day horizon, timekeeping, funding/loan policy and "
            "bounded telemetry cadence.",
            "All three original services retained; only extra engine123 vehicle on "
            "existing S2 or S3 infrastructure.",
            "Fresh matched A/B/C starts and construction/dispatch timing must be "
            "verified; historical A alone is not a matched control.",
        ],
        acceptance_criteria=[
            "Every arm completes 1826 economy days and verified original-service "
            "allocation; no lost/duplicated telemetry.",
            "Treatment target and network delivered cargo exceed matched A; report "
            "exact deltas and annual intervals.",
            "Network revenue exceeds matched A; service revenue remains UNKNOWN "
            "unless separately observed.",
            "Report fourth vehicle command-local CAPEX and observed cash/expense "
            "deltas with every unexplained residual UNKNOWN.",
            "Report queue exposure, censored interval delivery frequency, cycle load "
            "and observed idle/service durations; no inferred event timestamps "
            "treated as exact.",
        ],
        acceptance_thresholds={
            "target_cargo_delta_vs_matched_A": {"operator": ">", "value": 0},
            "network_cargo_delta_vs_matched_A": {"operator": ">", "value": 0},
            "network_revenue_delta_gbp_vs_matched_A": {"operator": ">", "value": 0},
            "extra_vehicles": 1,
            "economy_days_each_arm": 1826,
            "purchase_cost_ceiling_gbp": None,
            "purchase_cost_policy": "Require a fresh verified quote and explicit cost ceiling.",
            "economic_success": "UNKNOWN while incremental costs or residuals are unattributed.",
        },
        native_ready=False,
        execution_support="CONTROLLED_TESTED_ONE_ADDITIONAL_VEHICLE_WITH_INDEPENDENT_RECEIPT",
        telemetry_support="CONTROLLED_TESTED_EXISTING_SESSION_COLLECTION_AND_RAW_REPLAY",
        matched_source=matched_source,
        readiness_blockers=matched_source["blockers"]
        + [
            "Matched loading must verify a paused purchase boundary, supported command "
            "pause settings and coordinated unpause before continuous operation.",
            "Any native launch or Admin connection requires separate authorization.",
        ],
        limitations=[
            "P05 feasibility is one-trip capacity/resource/budget feasibility, not a "
            "five-year throughput or frequency forecast.",
            "Running-cost rate is not actual OPEX; no ROI, profit or service revenue invented.",
            "Monthly endpoint means are sampled queue exposure, not time-weighted "
            "continuous backlog.",
        ],
    )
