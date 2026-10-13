"""P07 multi-route planned metrics and conservatively attributed retained evidence."""

import json
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Literal

from app.experiments.freight_evaluation import FreightEvaluation, FreightMetric, evaluate_freight
from app.planning.canonical import plan_hash, scenario_hash
from app.planning.domain import Contract, Digest, ExecutionPlan, PlanningScenario, RoadFleetOption
from app.planning.validation import validate_execution_plan


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
            provenance="Subtotal of admitted service batches; "
            "failed/unattributed services excluded. "
            "Independent windows do not establish concurrent network performance.",
        )
        for name, unit in (
            ("delivered_cargo", "cargo_units"),
            ("vehicle_purchase", "GBP"),
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
    """Verify retained packages; never count independent historical runs as a network.

    Current native receipts prove single services. Multi-service actuals require
    exact network-plan binding and a common observation window. Until those exist,
    the network's actual metrics stay unknown, with planned CAPEX shown separately.
    """
    validate_execution_plan(plan, scenario)
    if plan.planner_inputs_digest != scenario_hash(scenario):
        raise ValueError("network plan input digest mismatch")
    native = None
    native_services = {}
    if native_network_directory is not None:
        from app.simulation.openttd.freight_native_network import verify_network_receipt

        native = verify_network_receipt(native_network_directory)
        if native["execution_plan_digest"] != plan_hash(plan):
            raise ValueError("native network receipt belongs to a different plan")
        native_services = {r["route_id"]: r for r in native["services"]}
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
        estimate = {
            "delivered_cargo": Decimal(assignment.quantity),
            "vehicles": Decimal(group.count),
            "vehicle_purchase": vehicle_purchase,
            "exclusive_infrastructure_capex": exclusive,
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
                native = json.loads((directories[route.route_id] / "plan.json").read_bytes())
                if (
                    f"industry-{receipt['source']}" != demand.origin_id
                    or f"industry-{receipt['destination']}" != demand.destination_id
                    or option.vehicle.vehicle_type != f"road-engine-{native['a'][3]}"
                    or receipt["cargo"] != native["a"][2]
                    or receipt["delivered"] > assignment.quantity
                    or group.count != 1
                ):
                    raise ValueError("verified receipt does not belong to selected service")
                if not evidence.receipt or evidence.history_key in seen_receipts:
                    raise ValueError("duplicate service receipt")
                seen_receipts.add(evidence.history_key)
                actual = {m.name: m for m in evidence.metrics}
                status = "verified-delivery"
        if route.route_id in native_services:
            retained = native_services[route.route_id]
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
            )
            actual = {
                name: FreightMetric(
                    name=name,
                    unit="cargo_units"
                    if name == "delivered_cargo"
                    else "vehicles"
                    if name == "vehicles"
                    else "GBP",
                    scope="service_batch",
                    actual=Decimal(value),
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
                    provenance=observed.provenance
                    if observed and amount is not None
                    else "Selected historical-batch estimate; no attributed native observation.",
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
                actual=(Decimal(native[name]) if native[name] is not None else None)
                if native is not None and name in native
                else (
                    Decimal(native["actual_capex"])
                    if native is not None and name == "total_capex"
                    else Decimal(native["delivered"])
                    if native is not None and name == "delivered_cargo"
                    else Decimal(native["payment_income"])
                    if native is not None and name == "delivery_revenue"
                    else Decimal(2)
                    if native is not None and name == "vehicles"
                    else None
                ),
                provenance="Verified unique native ledger; OPEX and net return unknown."
                if native is not None
                else "Unique selected construction actions and fleet purchases; "
                "actual network ledger unavailable.",
            )
        )
    return NetworkEvaluation(
        classification="NATIVE_MULTI_SERVICE_EVALUATION"
        if native
        else "CONTROLLED_MULTI_SERVICE_EVALUATION",
        native_execution_ready=native is not None,
        plan_digest=digest,
        scenario_digest=scenario_hash(scenario),
        services=tuple(services),
        metrics=tuple(network_metrics),
        verified_service_count=sum(s.status == "verified-delivery" for s in services),
        verified_batch_subtotals=verified_batch_subtotals(tuple(services)),
        limitations=(
            "Serial same-session services; concurrent throughput is unmeasured.",
            "Operating expenses and net return remain unknown.",
        )
        if native is not None
        else (
            "Historical qualified supply batch, not future production or measured acceptor demand.",
            "Native multi-service execution is unproven; "
            "the existing executor accepts one service.",
            "Independent runs and company income cannot be summed into network service revenue.",
            "Shared asset spending and a common network observation window "
            "require verified evidence.",
            "Operating expenses and net return remain unknown.",
        ),
    )
