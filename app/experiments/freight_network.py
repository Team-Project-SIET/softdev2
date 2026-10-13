"""P07 multi-route planned metrics and conservatively attributed retained evidence."""

import json
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Literal

from app.experiments.freight_evaluation import FreightEvaluation, FreightMetric, evaluate_freight
from app.planning.canonical import plan_hash, scenario_hash
from app.planning.domain import Contract, Digest, ExecutionPlan, PlanningScenario, RoadFleetOption
from app.planning.realized import ArtifactReference
from app.planning.validation import validate_execution_plan


class FeedbackFinding(Contract):
    code: str
    scope: str
    metric: str
    planned: Decimal | None = None
    actual: Decimal | None = None
    difference: Decimal | None = None
    evidence_refs: tuple[str, ...] = ()
    recommendation: str


class ServiceEvaluation(Contract):
    route_id: str
    demand_id: str
    status: Literal["unobserved", "failed", "unattributed", "verified-delivery"]
    evidence: FreightEvaluation | None = None
    metrics: tuple[FreightMetric, ...]


class NetworkEvaluation(Contract):
    classification: str = "CONTROLLED_MULTI_SERVICE_EVALUATION"
    native_execution_ready: bool = False
    plan_digest: Digest
    scenario_digest: Digest
    services: tuple[ServiceEvaluation, ...]
    metrics: tuple[FreightMetric, ...]
    verified_service_count: int
    verified_batch_subtotals: tuple[FreightMetric, ...]
    limitations: tuple[str, ...]
    evidence_directory: str | None = None
    evidence_refs: tuple[ArtifactReference, ...] = ()
    feedback: tuple[FeedbackFinding, ...] = ()


def verified_batch_subtotals(services: tuple[ServiceEvaluation, ...]) -> tuple[FreightMetric, ...]:
    """Aggregate admitted service batches, separately from a concurrent network window."""
    verified = [s for s in services if s.status == "verified-delivery"]
    values = [{m.name: m.actual for m in s.metrics} for s in verified]
    return tuple(
        FreightMetric(
            name=name,
            unit=unit,
            scope="verified_selected_service_batches",
            actual=sum((amount for v in values if (amount := v.get(name)) is not None), Decimal(0))
            if values and all(v.get(name) is not None for v in values)
            else None,
            provenance=(
                "Subtotal of admitted service batches; "
                "failed/unattributed services excluded. "
                "Independent windows do not establish concurrent network performance."
            ),
        )
        for name, unit in (
            ("delivered_cargo", "cargo_units"),
            ("vehicle_purchase", "GBP"),
            ("total_capex", "GBP"),
            ("delivery_revenue", "GBP"),
            ("vehicle_profit", "GBP"),
            ("operating_costs", "GBP"),
        )
    )


def evaluate_freight_network(
    plan: ExecutionPlan,
    scenario: PlanningScenario,
    service_directories: dict[str, Path] | None = None,
    *,
    native_network_directory: Path | None = None,
) -> NetworkEvaluation:
    """Verify retained packages; independent historical runs are never network actuals."""
    validate_execution_plan(plan, scenario)
    if plan.planner_inputs_digest != scenario_hash(scenario):
        raise ValueError("network plan input digest mismatch")
    native = None
    native_services = {}
    references = ()
    if native_network_directory is not None:
        from app.simulation.openttd.freight_native_network import verify_network_receipt

        native = verify_network_receipt(native_network_directory)
        if native["execution_plan_digest"] != plan_hash(plan):
            raise ValueError("native network receipt belongs to a different plan")
        native_services = {r["route_id"]: r for r in native["services"]}
        references = tuple(
            ArtifactReference(
                reference=name,
                sha256=sha256((native_network_directory / name).read_bytes()).hexdigest(),
            )
            for name in (
                "receipt.json",
                "execution-plan.json",
                "planning-scenario.json",
                *(
                    f"s{i}-{stage}-response.json"
                    for i in range(len(native_services))
                    for stage in ("observe-1", "finish")
                ),
                *(f"service-receipt-{i}.json" for i in range(len(native_services))),
            )
            if (native_network_directory / name).exists()
        )
        if set(native_services) != {r.route_id for r in plan.routes}:
            raise ValueError("native network services differ from selected plan")
    directories = service_directories or {}
    if native is not None and directories:
        raise ValueError("native network and historical service windows cannot be mixed")
    if not directories.keys() <= {r.route_id for r in plan.routes}:
        raise ValueError("evidence references an unselected service")
    digest = plan_hash(plan)
    options = {o.option_id: o for o in scenario.fleet_options}
    demands = {d.demand_id: d for d in scenario.cargo_demands}
    groups = {g.fleet_group_id: g for g in plan.fleet.groups}
    actions = {a.construction_id: a for a in plan.infrastructure.actions}
    seen_receipts = set()
    services = []
    purchase = Decimal(0)
    for route in plan.routes:
        group = groups[route.fleet_group_id]
        option = options[group.option_id]
        if not isinstance(option, RoadFleetOption) or len(route.cargo_assignments) != 1:
            raise ValueError("freight network evaluation requires direct road services")
        assignment = route.cargo_assignments[0]
        demand = demands[assignment.demand_id]
        vehicle_purchase = option.vehicle.purchase_cost_gbp * group.count
        purchase += vehicle_purchase
        # Shared asset CAPEX belongs to the network, never to every service total.
        exclusive = sum(
            (
                actions[a].estimated_build_cost_gbp
                for a in route.infrastructure_ids
                if len(actions[a].route_ids) == 1
            ),
            Decimal(0),
        )
        capacity = Decimal(option.vehicle.capacity_cargo_units * group.count)
        estimate = {
            "delivered_cargo": Decimal(assignment.quantity),
            "vehicles": Decimal(group.count),
            "vehicle_purchase": vehicle_purchase,
            "exclusive_infrastructure_capex": exclusive,
            "capacity_units": capacity,
            "capacity_utilization": Decimal(assignment.quantity) / capacity if capacity else None,
            "total_capex": exclusive + vehicle_purchase
            if all(len(actions[a].route_ids) == 1 for a in route.infrastructure_ids)
            else None,
        }
        evidence = (
            evaluate_freight(directories[route.route_id]) if route.route_id in directories else None
        )
        status = "unobserved"
        actual = {}
        if evidence is not None:
            status = "failed" if evidence.status == "failed" else "unattributed"
            if evidence.status == "verified-delivery" and evidence.execution_plan_digest == digest:
                receipt_bytes = (directories[route.route_id] / "receipt.json").read_bytes()
                if (
                    not evidence.receipt
                    or sha256(receipt_bytes).hexdigest() != evidence.receipt.sha256
                ):
                    raise ValueError("verified receipt changed during evaluation")
                receipt = json.loads(receipt_bytes)
                retained_scenario = PlanningScenario.model_validate_json(
                    (directories[route.route_id] / "planning-scenario.json").read_bytes()
                )
                if scenario_hash(retained_scenario) != scenario_hash(scenario):
                    raise ValueError("verified service cargo/scenario binding differs")
                native_plan = json.loads((directories[route.route_id] / "plan.json").read_bytes())
                if (
                    f"industry-{receipt['source']}" != demand.origin_id
                    or f"industry-{receipt['destination']}" != demand.destination_id
                    or option.vehicle.vehicle_type != f"road-engine-{native_plan['a'][3]}"
                    or receipt["cargo"] != native_plan["a"][2]
                    or receipt["delivered"] > assignment.quantity
                    or group.count != 1
                ):
                    raise ValueError("verified receipt does not belong to selected service")
                if not evidence.receipt or evidence.history_key in seen_receipts:
                    raise ValueError("duplicate service receipt")
                seen_receipts.add(evidence.history_key)
                actual = {m.name: m for m in evidence.metrics}
                status = "verified-delivery"
        if (
            native is not None
            and native_network_directory is not None
            and route.route_id in native_services
        ):
            retained = native_services[route.route_id]
            service_index = next(
                i for i, r in enumerate(native["services"]) if r["route_id"] == route.route_id
            )
            loaded_path = native_network_directory / f"s{service_index}-observe-1-response.json"
            finish_path = native_network_directory / f"s{service_index}-finish-response.json"
            loaded = json.loads(loaded_path.read_bytes())["s"] if loaded_path.exists() else None
            finished = json.loads(finish_path.read_bytes())["s"] if finish_path.exists() else None
            stage_costs = retained["mutation_costs"]
            from app.simulation.openttd.freight_native_network import stage_assets

            mapped = stage_assets(plan, route.route_id)
            exclusive_actual = sum(
                stage_costs[i] for i, asset in mapped.items() if len(actions[asset].route_ids) == 1
            )
            observed_values = dict(
                delivered_cargo=retained["delivered"],
                vehicles=1,
                vehicle_purchase=stage_costs[6],
                exclusive_infrastructure_capex=exclusive_actual,
                delivery_revenue=retained["payment_income"],
                vehicle_profit=retained["vehicle_profit_delta"],
                total_capex=exclusive_actual + stage_costs[6]
                if all(len(actions[a].route_ids) == 1 for a in route.infrastructure_ids)
                else None,
                capacity_units=loaded[7] if loaded else None,
                load_fill=Decimal(loaded[11]) / loaded[7] if loaded and loaded[7] else None,
                source_waiting=finished[15] if finished else None,
                capacity_utilization=Decimal(retained["delivered"]) / capacity
                if capacity
                else None,
            )
            actual = {
                name: FreightMetric(
                    name=name,
                    unit="cargo_units"
                    if name in {"delivered_cargo", "capacity_units", "source_waiting"}
                    else "vehicles"
                    if name == "vehicles"
                    else "ratio"
                    if name in {"capacity_utilization", "load_fill"}
                    else "GBP",
                    scope="service_batch",
                    actual=Decimal(value) if value is not None else None,
                    provenance="Native readbacks; only this vehicle runs in the payment window.",
                )
                for name, value in observed_values.items()
            }
            status = "verified-delivery"
        metrics = []
        for name, unit in (
            ("delivered_cargo", "cargo_units"),
            ("vehicles", "vehicles"),
            ("vehicle_purchase", "GBP"),
            ("exclusive_infrastructure_capex", "GBP"),
            ("total_capex", "GBP"),
            ("capacity_units", "cargo_units"),
            ("capacity_utilization", "ratio"),
            ("load_fill", "ratio"),
            ("source_waiting", "cargo_units"),
            ("delivery_revenue", "GBP"),
            ("vehicle_profit", "GBP"),
            ("operating_costs", "GBP"),
            ("net_return", "GBP"),
        ):
            observed = actual.get(name)
            # Current revenue is company-level; concurrent service attribution is unavailable.
            amount = (
                observed.actual
                if observed
                and (
                    native is not None
                    or name not in {"delivery_revenue", "operating_costs", "net_return"}
                )
                else None
            )
            planned = estimate.get(name)
            metrics.append(
                FreightMetric(
                    name=name,
                    unit=unit,
                    scope="service_batch",
                    actual=amount,
                    planned=planned,
                    comparison="comparable"
                    if planned is not None and amount is not None
                    else "unavailable",
                    difference=amount - planned
                    if planned is not None and amount is not None
                    else None,
                    provenance=(
                        "Verified delivered batch / selected planned fleet capacity; "
                        "not load factor or throughput."
                    )
                    if name == "capacity_utilization" and amount is not None
                    else (
                        "Loaded snapshot cargo / measured vehicle capacity; "
                        "one snapshot, not time utilization."
                    )
                    if name == "load_fill" and amount is not None
                    else "Measured vehicle capacity at the loaded snapshot."
                    if name == "capacity_units" and amount is not None
                    else "Cargo waiting at source station at final delivery snapshot."
                    if name == "source_waiting" and amount is not None
                    else observed.provenance
                    if observed and amount is not None
                    else ("Selected historical-batch estimate; no attributed native observation."),
                )
            )
        services.append(
            ServiceEvaluation(
                route_id=route.route_id,
                demand_id=demand.demand_id,
                status=status,
                evidence=evidence,
                metrics=tuple(metrics),
            )
        )
    infrastructure = sum(
        (a.estimated_build_cost_gbp for a in plan.infrastructure.actions), Decimal(0)
    )
    planned = {
        "delivered_cargo": Decimal(
            sum(a.quantity for r in plan.routes for a in r.cargo_assignments)
        ),
        "vehicles": Decimal(sum(g.count for g in plan.fleet.groups)),
        "infrastructure_capex": infrastructure,
        "vehicle_purchase": purchase,
        "total_capex": infrastructure + purchase,
    }
    native_actual = (
        {}
        if native is None
        else {
            "delivered_cargo": Decimal(native["delivered"]),
            "vehicles": Decimal(len(native_services)),
            "infrastructure_capex": Decimal(native["infrastructure_capex"]),
            "vehicle_purchase": Decimal(native["vehicle_purchase"]),
            "total_capex": Decimal(native["actual_capex"]),
            "delivery_revenue": Decimal(native["payment_income"]),
            "vehicle_profit": sum(
                (Decimal(r["vehicle_profit_delta"]) for r in native_services.values()), Decimal(0)
            ),
        }
    )
    network_metrics = []
    for name, unit in (
        ("delivered_cargo", "cargo_units"),
        ("vehicles", "vehicles"),
        ("infrastructure_capex", "GBP"),
        ("vehicle_purchase", "GBP"),
        ("total_capex", "GBP"),
        ("delivery_revenue", "GBP"),
        ("vehicle_profit", "GBP"),
        ("operating_costs", "GBP"),
        ("net_return", "GBP"),
    ):
        # Independent single-service runs cannot demonstrate one network window or shared spending.
        network_metrics.append(
            FreightMetric(
                name=name,
                unit=unit,
                scope="network_batch",
                planned=planned.get(name),
                actual=native_actual.get(name),
                provenance="Verified unique native ledger; OPEX and net return unknown."
                if native is not None
                else "Unique selected construction actions and fleet purchases; "
                "actual network ledger unavailable.",
            )
        )
    network_metrics = [
        m.model_copy(update={"comparison": "comparable", "difference": m.actual - m.planned})
        if m.actual is not None and m.planned is not None
        else m
        for m in network_metrics
    ]
    return NetworkEvaluation(
        classification="NATIVE_MULTI_SERVICE_EVALUATION"
        if native
        else "CONTROLLED_MULTI_SERVICE_EVALUATION",
        native_execution_ready=native is not None,
        plan_digest=digest,
        scenario_digest=scenario_hash(scenario),
        services=tuple(services),
        evidence_directory=str(native_network_directory.resolve())
        if native_network_directory
        else None,
        evidence_refs=references,
        feedback=optimization_feedback(
            tuple(services), tuple(network_metrics), references, native is not None
        ),
        metrics=tuple(network_metrics),
        verified_service_count=sum(s.status == "verified-delivery" for s in services),
        verified_batch_subtotals=verified_batch_subtotals(tuple(services)),
        limitations=(
            ("Serial same-session services; concurrent throughput is unmeasured."),
            "Operating expenses and net return remain unknown.",
        )
        if native is not None
        else (
            (
                "Historical qualified supply batch, not future production or "
                "measured acceptor demand."
            ),
            "Native multi-service execution is unproven; "
            "this controlled plan has no verified native network package.",
            ("Independent runs and company income cannot be summed into network service revenue."),
            "Shared asset spending and a common network observation window "
            "require verified evidence.",
            "Operating expenses and net return remain unknown.",
        ),
    )


def optimization_feedback(services, metrics, references, native_verified):
    """Report deterministic recommendations; never change planner parameters."""
    findings = []
    refs = tuple(r.reference for r in references)
    scopes = (("network", metrics), *((s.route_id, s.metrics) for s in services))
    for scope, rows in scopes:
        for metric in rows:
            if metric.name in {
                "infrastructure_capex",
                "exclusive_infrastructure_capex",
                "vehicle_purchase",
                "total_capex",
            } and metric.difference not in {None, Decimal(0)}:
                code = "cost_estimation_error"
                recommendation = (
                    "P08: inspect command costs against candidate estimates. "
                    "Validate additional comparable runs before changing P05 cost inputs."
                )
            elif metric.name == "capacity_utilization" and metric.actual is not None:
                code = "batch_capacity_utilization"
                recommendation = (
                    "P05: compare batch size and selected fleet capacity. "
                    "This ratio does not measure load factor or concurrent throughput. "
                    "Observe repeat trips before resizing fleets."
                )
            elif metric.name == "source_waiting" and metric.actual not in {None, Decimal(0)}:
                code = "source_waiting_backlog"
                recommendation = (
                    "P08/P05: observe repeat-trip queue growth and service frequency "
                    "before expanding the fleet. One waiting snapshot does not prove "
                    "sustained unmet demand."
                )
            else:
                continue
            findings.append(
                FeedbackFinding(
                    code=code,
                    scope=scope,
                    metric=metric.name,
                    planned=metric.planned,
                    actual=metric.actual,
                    difference=metric.difference,
                    evidence_refs=refs,
                    recommendation=recommendation,
                )
            )
    if native_verified:
        for code, recommendation in (
            (
                "collect_opex",
                (
                    "P07: collect complete attributed expenses and matching windows "
                    "before ranking net returns. Revenue minus vehicle profit is not full OPEX."
                ),
            ),
            (
                "validate_shared_assets",
                (
                    "P08/P05: validate paid shared-asset reuse with unique construction "
                    "ledgers before assuming network savings."
                ),
            ),
            (
                "validate_concurrency",
                (
                    "P05: validate simultaneous services before treating serial "
                    "delivery batches as concurrent capacity evidence."
                ),
            ),
        ):
            findings.append(
                FeedbackFinding(
                    code=code,
                    scope="network",
                    metric="operating_costs" if code == "collect_opex" else "unproven_capability",
                    evidence_refs=refs,
                    recommendation=recommendation,
                )
            )
    return tuple(findings)
