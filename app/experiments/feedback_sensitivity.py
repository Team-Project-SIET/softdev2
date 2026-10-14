"""Bounded exhaustive, offline P05 budget sensitivity with unchanged objectives."""

from decimal import Decimal, localcontext
from itertools import product
from math import prod

from app.planning.canonical import scenario_hash
from app.planning.domain import PlanningScenario, RailComposition, RoadFleetOption
from app.planning.optimizer import (
    OptimizerFailure,
    OptimizerFailureCode,
    _alternatives,
    _emit,
    optimize_candidate_network,
)
from app.planning.validation import PlanningValidationError, validate_execution_plan


def _budget(scenario: PlanningScenario, budget: Decimal | None) -> PlanningScenario:
    return scenario.model_copy(
        update={"constraints": scenario.constraints.model_copy(update={"budget_gbp": budget})}
    )


def _summary(scenario: PlanningScenario, budget: Decimal) -> dict:
    variant = _budget(scenario, budget)
    try:
        result = optimize_candidate_network(variant)
    except OptimizerFailure as error:
        if error.code not in (
            OptimizerFailureCode.GLOBALLY_INFEASIBLE,
            OptimizerFailureCode.BUDGET_INFEASIBLE,
        ):
            raise
        return dict(feasible=False, failure_code=error.code.value, selected_services=[])
    plan = result.plan
    validate_execution_plan(plan, variant)
    options = {o.option_id: o for o in variant.fleet_options}
    demands = {d.demand_id: d for d in variant.cargo_demands}
    services = sorted(a.demand_id for r in plan.routes for a in r.cargo_assignments)
    cargo = sum(demands[d].quantity for d in services)
    infrastructure = sum(
        (a.estimated_build_cost_gbp for a in plan.infrastructure.actions), Decimal(0)
    )
    purchase = result.metrics.vehicle_purchase_cost_gbp
    assert purchase is not None
    capex = infrastructure + purchase

    def group_capacity(group) -> int:
        option = options[group.option_id]
        if isinstance(option, RoadFleetOption):
            return group.count * option.vehicle.capacity_cargo_units
        assert isinstance(group.composition, RailComposition)
        return group.count * group.composition.total_capacity_cargo_units

    capacity = sum(group_capacity(g) for g in plan.fleet.groups)
    network = variant.constraints.network_selection
    assert network is not None
    action_ids = {a.construction_id: a.candidate_id for a in plan.infrastructure.actions}
    resource_use = {
        limit.candidate_id: sum(
            g.count
            for g in plan.fleet.groups
            if any(
                r.fleet_group_id == g.fleet_group_id
                and limit.candidate_id in {action_ids[a] for a in r.infrastructure_ids}
                for r in plan.routes
            )
        )
        for limit in network.resource_limits
    }
    return dict(
        feasible=True,
        independently_validated=True,
        selected_services=services,
        selected_candidate_ids=sorted(a.candidate_id for a in plan.infrastructure.actions),
        estimated_capex_gbp=str(capex),
        infrastructure_capex_gbp=str(infrastructure),
        vehicle_purchase_gbp=str(purchase),
        capacity_cargo_units=capacity,
        served_demand_units=cargo,
        vehicles=sum(g.count for g in plan.fleet.groups),
        objective=dict(maximize_served_cargo_units=cargo, minimize_capex_gbp=str(capex)),
        slack=dict(
            budget_gbp=str(budget - capex),
            capacity_cargo_units={
                g.fleet_group_id: group_capacity(g) * g.planned_trips_per_vehicle
                - sum(demands[d].quantity for d in g.demand_ids)
                for g in plan.fleet.groups
            },
            vehicles=network.max_vehicles - sum(g.count for g in plan.fleet.groups),
            supplies=[
                dict(
                    origin_id=s.origin_id,
                    cargo_type=s.cargo_type,
                    quantity=s.quantity
                    - sum(
                        demands[d].quantity
                        for d in services
                        if demands[d].origin_id == s.origin_id
                        and demands[d].cargo_type == s.cargo_type
                    ),
                )
                for s in network.supplies
            ],
            resources={
                r.candidate_id: r.max_vehicles - resource_use[r.candidate_id]
                for r in network.resource_limits
            },
        ),
    )


def analyze_sensitivity(
    scenarios: dict[str, PlanningScenario], *, max_combinations: int = 100000
) -> dict:
    """Enumerate every eligible alternative combination; fail rather than truncate."""
    if "baseline" not in scenarios or len(scenarios) < 2:
        raise ValueError("baseline and at least one feedback scenario required")
    if max_combinations < 1:
        raise ValueError("max_combinations must be positive")
    with localcontext() as context:
        context.prec = 100
        return _analyze(scenarios, max_combinations)


def _analyze(scenarios: dict[str, PlanningScenario], maximum: int) -> dict:
    def fixed_inputs(scenario: PlanningScenario) -> dict:
        value = scenario.model_dump(mode="json")
        value["constraints"].pop("budget_gbp")
        for candidate in value["infrastructure_candidates"]:
            candidate.pop("estimated_build_cost_gbp")
        return value

    scenarios = {
        name: PlanningScenario.model_validate_json(s.model_dump_json())
        for name, s in scenarios.items()
    }
    baseline_inputs = fixed_inputs(scenarios["baseline"])
    if any(fixed_inputs(s) != baseline_inputs for s in scenarios.values()):
        raise ValueError("sensitivity variants may differ only in infrastructure cost and budget")
    thresholds = {Decimal(0)}
    inventory = {}
    for name, scenario in scenarios.items():
        if scenario.constraints.network_selection is None:
            raise ValueError("sensitivity requires existing network-selection constraints")
        unrestricted = _budget(scenario, None)
        alternatives = _alternatives(unrestricted)
        count = prod(len(items) + 1 for items in alternatives)
        if count > maximum:
            raise ValueError(f"{name}: {count} combinations exceed bound {maximum}")
        eligible = []
        rejected = 0
        for combination in product(*[(None, *items) for items in alternatives]):
            selected = [a for a in combination if a is not None]
            if not selected:
                continue
            plan = _emit(unrestricted, selected)
            try:
                validate_execution_plan(plan, unrestricted)
            except PlanningValidationError:
                rejected += 1
                continue
            infrastructure = sum(
                (a.estimated_build_cost_gbp for a in plan.infrastructure.actions), Decimal(0)
            )
            purchase = sum((a.purchase_cost for a in selected), Decimal(0))
            cost = infrastructure + purchase
            thresholds.add(cost)
            eligible.append(
                dict(
                    selected_services=sorted(a.demand.demand_id for a in selected),
                    selected_candidate_ids=sorted(
                        a.candidate_id for a in plan.infrastructure.actions
                    ),
                    estimated_capex_gbp=str(cost),
                    infrastructure_capex_gbp=str(infrastructure),
                    vehicle_purchase_gbp=str(purchase),
                )
            )
        inventory[name] = dict(
            enumerated_combinations=count,
            empty_combinations=1,
            rejected_nonbudget_constraints=rejected,
            eligible_combinations=eligible,
        )
    ordered = sorted(thresholds)
    # Midpoints cover the immediately preceding open intervals without rounding.
    budgets = sorted(
        set(
            ordered
            + [(a + b) / 2 for a, b in zip(ordered, ordered[1:])]
            + [
                s.constraints.budget_gbp
                for s in scenarios.values()
                if s.constraints.budget_gbp is not None
            ]
        )
    )
    rows: list[dict] = [
        dict(
            budget_gbp=str(budget),
            variants={name: _summary(scenario, budget) for name, scenario in scenarios.items()},
        )
        for budget in budgets
    ]
    by_budget = {Decimal(row["budget_gbp"]): row for row in rows}
    differences = []
    feasibility = []
    for index, lower in enumerate(ordered):
        upper = ordered[index + 1] if index + 1 < len(ordered) else None
        variants = by_budget[lower]["variants"]
        baseline = variants["baseline"]
        for name, feedback in variants.items():
            if name == "baseline":
                continue
            interval = dict(
                feedback_scenario=name,
                lower_inclusive_gbp=str(lower),
                upper_exclusive_gbp=str(upper) if upper is not None else None,
                baseline=baseline,
                feedback=feedback,
                metrics_budget_gbp=str(lower),
            )
            if baseline["feasible"] != feedback["feasible"]:
                feasibility.append(interval)
            elif (
                baseline["feasible"]
                and baseline["selected_services"] != feedback["selected_services"]
            ):
                differences.append(interval)
    return dict(
        classification="CONTROLLED_FEEDBACK_DECISION_SENSITIVITY",
        native_launches=0,
        bounds=dict(
            min_budget_gbp="0",
            max_tested_budget_gbp=str(budgets[-1]),
            higher_budgets="same choices: every eligible combination already affordable",
            max_combinations_per_scenario=maximum,
            exhaustive=True,
            budget_sampling="exact Decimal thresholds and preceding interval midpoints",
        ),
        objective="unchanged P05: maximize cargo, minimize CAPEX, canonical alternative tie-break",
        assumptions=[
            "Only budget varies; candidates, fleet and nonbudget constraints stay fixed.",
            "Infrastructure is counted once per unique candidate id; vehicles per fleet group.",
            "Capacity is per load; served demand is supplied planning-horizon demand.",
            "Attempt 12 costs are retrospective feedback, not independent validation.",
            "Observed-error and double-error are supplied uplift scenarios, not predictions.",
            "OPEX, profitability, ROI and fresh native A/B outcomes remain unknown.",
        ],
        scenario_digests={name: scenario_hash(s) for name, s in scenarios.items()},
        scenarios=inventory,
        budget_grid=[str(b) for b in budgets],
        rows=rows,
        decision_intervals=differences,
        feasibility_intervals=feasibility,
        decision_differences_found=bool(differences),
    )
