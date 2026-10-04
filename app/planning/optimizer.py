"""P05: select supplied direct corridors and fleets, without vehicle pathfinding."""

from dataclasses import dataclass
from decimal import Decimal, localcontext
from enum import StrEnum
from hashlib import sha256
from itertools import product

from ortools.sat.python import cp_model
from pydantic import ValidationError

from app.planning.canonical import canonical_bytes, plan_hash, scenario_hash
from app.planning.domain import (
    CargoAssignment,
    CargoDemand,
    Composition,
    ConstructionAction,
    ConstructionKind,
    EstimatedPlanMetrics,
    ExecutionPlan,
    FleetGroup,
    FleetPlan,
    InfrastructureCandidate,
    InfrastructurePlan,
    Mode,
    PlanningScenario,
    RailComposition,
    RailFleetOption,
    RoadComposition,
    RoadFleetOption,
    RoutePlan,
    RouteStop,
    StopRole,
    ValidationDeclaration,
    WagonComposition,
)
from app.planning.validation import PlanningValidationError, validate_execution_plan


class OptimizerFailureCode(StrEnum):
    NO_FEASIBLE_STATION_PAIR = "no_feasible_station_pair"
    NO_CONNECTING_SEGMENT = "no_connecting_segment"
    NO_COMPATIBLE_FLEET = "no_compatible_fleet"
    RAIL_CONSIST_INFEASIBLE = "rail_consist_infeasible"
    BUDGET_INFEASIBLE = "budget_infeasible"
    GLOBALLY_INFEASIBLE = "globally_infeasible"
    UNSUPPORTED_SCENARIO = "unsupported_scenario"


class OptimizerFailure(ValueError):
    def __init__(self, code: OptimizerFailureCode, detail: str) -> None:
        self.code = code
        super().__init__(detail)


@dataclass(frozen=True)
class OptimizationResult:
    plan: ExecutionPlan
    metrics: EstimatedPlanMetrics


@dataclass(frozen=True)
class _Alternative:
    demand: CargoDemand
    candidates: tuple[InfrastructureCandidate, ...]  # pickup, delivery, depot, segment
    option_id: str
    composition: Composition
    count: int
    start_day: int
    purchase_cost: Decimal

    @property
    def key(self) -> tuple[str, ...]:
        return tuple(c.candidate_id for c in self.candidates) + (
            self.option_id,
            canonical_bytes(self.composition).decode(),
        )


def _id(kind: str, identity: str) -> str:
    return f"p05-{kind}-{sha256(identity.encode()).hexdigest()}"


def _emit(scenario: PlanningScenario, chosen: list[_Alternative]) -> ExecutionPlan:
    routes = []
    groups = []
    users: dict[str, list[str]] = {}
    selected: dict[str, InfrastructureCandidate] = {}
    for alternative in chosen:
        demand = alternative.demand
        pickup, delivery, depot, segment = alternative.candidates
        route_id = _id("route", demand.demand_id)
        group_id = _id("fleet", demand.demand_id)
        for candidate in alternative.candidates:
            selected[candidate.candidate_id] = candidate
            users.setdefault(candidate.candidate_id, []).append(route_id)
        assert pickup.site_id is not None and delivery.site_id is not None
        assert depot.site_id is not None
        routes.append(
            RoutePlan(
                route_id=route_id,
                mode=segment.mode,
                path_kind="station_to_station_intent",
                origin_id=demand.origin_id,
                destination_id=demand.destination_id,
                stops=(
                    RouteStop(location_id=pickup.site_id, role=StopRole.PICKUP),
                    RouteStop(location_id=delivery.site_id, role=StopRole.DELIVERY),
                    RouteStop(location_id=depot.site_id, role=StopRole.DEPOT),
                ),
                cargo_assignments=(
                    CargoAssignment(
                        demand_id=demand.demand_id, quantity=demand.quantity, unit=demand.unit
                    ),
                ),
                fleet_group_id=group_id,
                infrastructure_ids=tuple(
                    _id("build", c.candidate_id) for c in alternative.candidates
                ),
            )
        )
        groups.append(
            FleetGroup(
                fleet_group_id=group_id,
                mode=segment.mode,
                option_id=alternative.option_id,
                count=alternative.count,
                route_ids=(route_id,),
                demand_ids=(demand.demand_id,),
                start_day=alternative.start_day,
                order_mode="repeat_service",
                planned_trips_per_vehicle=1,
                composition=alternative.composition,
            )
        )
    order = {ConstructionKind.STATION: 0, ConstructionKind.DEPOT: 1, ConstructionKind.SEGMENT: 2}
    actions = []
    for candidate in sorted(selected.values(), key=lambda c: (order[c.kind], c.candidate_id)):
        dependencies = ()
        if candidate.kind is ConstructionKind.SEGMENT:
            dependencies = tuple(
                sorted(
                    _id("build", c.candidate_id)
                    for c in selected.values()
                    if c.kind is ConstructionKind.STATION
                    and c.mode == candidate.mode
                    and c.site_id in (candidate.origin_id, candidate.destination_id)
                )
            )
        actions.append(
            ConstructionAction(
                construction_id=_id("build", candidate.candidate_id),
                candidate_id=candidate.candidate_id,
                mode=candidate.mode,
                kind=candidate.kind,
                depends_on=dependencies,
                route_ids=tuple(sorted(users[candidate.candidate_id])),
                estimated_build_cost_gbp=candidate.estimated_build_cost_gbp,
            )
        )
    digest = scenario_hash(scenario)
    return ExecutionPlan(
        schema_version=1,
        plan_id=_id("plan", digest),
        scenario_id=scenario.scenario_id,
        scenario_version=scenario.scenario_version,
        world_fingerprint=scenario.world_fingerprint,
        planner_name="candidate-network-optimizer",
        planner_version="1",
        strategy_identifier="min-capex",
        strategy_version="1",
        planner_inputs_digest=digest,
        routes=tuple(sorted(routes, key=lambda r: r.route_id)),
        fleet=FleetPlan(groups=tuple(sorted(groups, key=lambda g: g.fleet_group_id))),
        infrastructure=InfrastructurePlan(actions=tuple(actions)),
        validation=ValidationDeclaration(
            validator_version="1",
            supported_modes=tuple(sorted(scenario.constraints.permitted_modes)),
            validated_world_fingerprint=scenario.world_fingerprint,
        ),
    )


def _rail_fleet(
    scenario: PlanningScenario, option: RailFleetOption, demand: CargoDemand, platform_limit: int
) -> tuple[RailComposition, int, Decimal] | None:
    limit = min(
        option.max_train_length_tiles,
        platform_limit,
        scenario.constraints.max_train_length_tiles or option.max_train_length_tiles,
    )
    locomotive_length = option.locomotive.length_tiles
    if locomotive_length is None:
        return None
    remaining = limit - locomotive_length
    wagons = sorted(
        (
            w
            for w in option.wagon_options
            if demand.cargo_type in w.compatible_cargo_types
            and w.capacity_cargo_units > 0
            and w.length_tiles is not None
        ),
        key=lambda w: w.vehicle_type,
    )
    if len(wagons) > 128:
        raise OptimizerFailure(
            OptimizerFailureCode.UNSUPPORTED_SCENARIO,
            f"{demand.demand_id}/{option.option_id}: "
            "rail catalog exceeds 128 compatible wagon types",
        )
    if not wagons or remaining <= 0:
        return None
    best: tuple[Decimal, bytes, RailComposition, int] | None = None
    visited = 0

    def search(
        index: int, counts: tuple[int, ...], length: int, capacity: int, cost: Decimal
    ) -> None:
        nonlocal best, visited
        visited += 1
        if visited > 100_000:
            raise OptimizerFailure(
                OptimizerFailureCode.UNSUPPORTED_SCENARIO,
                f"{demand.demand_id}/{option.option_id}: rail search exceeds 100000 states",
            )
        if index == len(wagons):
            if capacity == 0:
                return
            composition = RailComposition(
                mode=Mode.RAIL,
                locomotive_type=option.locomotive.vehicle_type,
                wagons=tuple(
                    WagonComposition(wagon_type=w.vehicle_type, count=n)
                    for w, n in zip(wagons, counts, strict=True)
                    if n
                ),
                total_capacity_cargo_units=capacity,
                total_length_tiles=locomotive_length + length,
            )
            count = (demand.quantity + capacity - 1) // capacity
            purchase = (option.locomotive.purchase_cost_gbp + cost) * count
            key = (purchase, canonical_bytes(composition))
            if best is None or key < best[:2]:
                best = (purchase, key[1], composition, count)
            return
        wagon = wagons[index]
        assert wagon.length_tiles is not None
        for count in range((remaining - length) // wagon.length_tiles + 1):
            search(
                index + 1,
                counts + (count,),
                length + count * wagon.length_tiles,
                capacity + count * wagon.capacity_cargo_units,
                cost + count * wagon.purchase_cost_gbp,
            )

    search(0, (), 0, 0, Decimal(0))
    if best is None:
        return None
    return best[2], best[3], best[0]


def _alternatives(scenario: PlanningScenario) -> list[list[_Alternative]]:
    locations = {s.location_id: s for s in scenario.locations}
    candidates = sorted(scenario.infrastructure_candidates, key=lambda c: c.candidate_id)
    modes = set(scenario.constraints.permitted_modes)
    stations = [c for c in candidates if c.kind is ConstructionKind.STATION and c.mode in modes]
    depots = [c for c in candidates if c.kind is ConstructionKind.DEPOT and c.mode in modes]
    # Directed supplied graph edges; retain the original candidate, including tiles and costs.
    edges: dict[tuple[str | None, str | None, Mode], list[InfrastructureCandidate]] = {}
    for c in candidates:
        if c.kind is ConstructionKind.SEGMENT:
            edges.setdefault((c.origin_id, c.destination_id, c.mode), []).append(c)
    result = []
    for demand in sorted(scenario.cargo_demands, key=lambda d: d.demand_id):
        pairs = [
            (a, b)
            for a, b in product(stations, repeat=2)
            if a.mode == b.mode
            and a.site_id in locations
            and b.site_id in locations
            and locations[a.site_id].serves_location_id == demand.origin_id
            and locations[b.site_id].serves_location_id == demand.destination_id
        ]
        if not pairs:
            raise OptimizerFailure(OptimizerFailureCode.NO_FEASIBLE_STATION_PAIR, demand.demand_id)
        connected = [
            (a, b, edge) for a, b in pairs for edge in edges.get((a.site_id, b.site_id, a.mode), [])
        ]
        if not connected:
            raise OptimizerFailure(OptimizerFailureCode.NO_CONNECTING_SEGMENT, demand.demand_id)
        alternatives = []
        rail_infeasible = False
        for a, b, edge in connected:
            assert a.site_id is not None and b.site_id is not None
            for depot, option in product(
                depots, sorted(scenario.fleet_options, key=lambda o: o.option_id)
            ):
                if option.mode != edge.mode:
                    continue
                if depot.mode != edge.mode or depot.site_id not in locations:
                    continue
                start = max(demand.earliest_day, option.available_from_day)
                if start > min(demand.latest_delivery_day, option.available_through_day):
                    continue
                if isinstance(option, RoadFleetOption):
                    if locations[depot.site_id].facility_class != option.depot_class:
                        continue
                    vehicle = option.vehicle
                    if (
                        demand.cargo_type not in vehicle.compatible_cargo_types
                        or vehicle.capacity_cargo_units == 0
                    ):
                        continue
                    count = (
                        demand.quantity + vehicle.capacity_cargo_units - 1
                    ) // vehicle.capacity_cargo_units
                    composition: Composition = RoadComposition(
                        mode=Mode.ROAD, vehicle_type=vehicle.vehicle_type
                    )
                    purchase = vehicle.purchase_cost_gbp * count
                else:
                    if locations[depot.site_id].facility_class != "rail":
                        continue
                    if edge.rail_type != option.rail_type or any(
                        c.rail_type is not None and c.rail_type != option.rail_type
                        for c in (a, b, depot)
                    ):
                        continue
                    if not any(
                        demand.cargo_type in w.compatible_cargo_types for w in option.wagon_options
                    ):
                        continue
                    platform = min(
                        locations[a.site_id].platform_length_tiles or 0,
                        locations[b.site_id].platform_length_tiles or 0,
                    )
                    rail = _rail_fleet(scenario, option, demand, platform)
                    if rail is None:
                        rail_infeasible = True
                        continue
                    composition, count, purchase = rail
                alternatives.append(
                    _Alternative(
                        demand,
                        (a, b, depot, edge),
                        option.option_id,
                        composition,
                        count,
                        start,
                        purchase,
                    )
                )
        if not alternatives:
            raise OptimizerFailure(
                OptimizerFailureCode.RAIL_CONSIST_INFEASIBLE
                if rail_infeasible
                else OptimizerFailureCode.NO_COMPATIBLE_FLEET,
                demand.demand_id,
            )
        result.append(sorted(alternatives, key=lambda a: a.key))
    return result


def _construction_conflicts(
    scenario: PlanningScenario, candidates: list[InfrastructureCandidate]
) -> list[tuple[str, str]]:
    locations = {s.location_id: s for s in scenario.locations}
    footprints: dict[str, set[tuple[int, int]]] = {}
    for c in candidates:
        if c.kind is ConstructionKind.SEGMENT:
            footprint = {(t.x, t.y) for t in c.tiles}
        else:
            assert c.site_id is not None
            tile = locations[c.site_id].tile
            footprint = {
                (x, y)
                for x in range(tile.x, tile.x + (c.footprint_width_tiles or 1))
                for y in range(tile.y, tile.y + (c.footprint_height_tiles or 1))
            }
        footprints[c.candidate_id] = footprint
    conflicts = []
    for i, a in enumerate(candidates):
        for b in candidates[i + 1 :]:
            # P02 allows station endpoints on corridors, but no other build overlap.
            station_segment = {a.kind, b.kind} == {
                ConstructionKind.STATION,
                ConstructionKind.SEGMENT,
            }
            if not station_segment and footprints[a.candidate_id] & footprints[b.candidate_id]:
                conflicts.append((a.candidate_id, b.candidate_id))
    return conflicts


def _cost_units(amounts: list[Decimal]) -> list[int]:
    """Exact GBP units: 10**max(2, fractional digits), at most 18; never round.

    A conservative signed-int64 bound covers every objective term simultaneously.
    Trailing zero spelling does not change the scale. Oversized inputs fail typed.
    """
    ratios = [a.as_integer_ratio() for a in amounts]
    places = 2
    for amount in amounts:
        digits = list(amount.as_tuple().digits)
        exponent = amount.as_tuple().exponent
        assert isinstance(exponent, int)
        while digits and digits[-1] == 0:
            digits.pop()
            exponent += 1
        if digits:
            places = max(places, -exponent)
    if places > 18:
        raise OptimizerFailure(
            OptimizerFailureCode.UNSUPPORTED_SCENARIO, "GBP precision exceeds 18 fractional digits"
        )
    scale = 10**places
    units = [numerator * scale // denominator for numerator, denominator in ratios]
    if any(n < 0 for n in units) or sum(units) >= 2**62:
        raise OptimizerFailure(
            OptimizerFailureCode.UNSUPPORTED_SCENARIO,
            "GBP costs exceed conservative CP-SAT integer range",
        )
    return units


def _solve(
    scenario: PlanningScenario, alternatives: list[list[_Alternative]]
) -> list[_Alternative]:
    model = cp_model.CpModel()
    choices = [
        [model.new_bool_var(f"a-{d}-{i}") for i in range(len(items))]
        for d, items in enumerate(alternatives)
    ]
    candidates = sorted(
        {c.candidate_id: c for items in alternatives for a in items for c in a.candidates}.values(),
        key=lambda c: c.candidate_id,
    )
    builds = {c.candidate_id: model.new_bool_var(f"c-{i}") for i, c in enumerate(candidates)}
    for items, variables in zip(alternatives, choices, strict=True):
        model.add_exactly_one(variables)
        for alternative, variable in zip(items, variables, strict=True):
            for c in alternative.candidates:
                model.add(variable <= builds[c.candidate_id])
    for c in candidates:
        model.add(
            builds[c.candidate_id]
            <= sum(
                variable
                for items, variables in zip(alternatives, choices, strict=True)
                for a, variable in zip(items, variables, strict=True)
                if c in a.candidates
            )
        )
    for a, b in _construction_conflicts(scenario, candidates):
        model.add(builds[a] + builds[b] <= 1)
    flat = [
        (a, v)
        for items, variables in zip(alternatives, choices, strict=True)
        for a, v in zip(items, variables, strict=True)
    ]
    amounts = [c.estimated_build_cost_gbp for c in candidates] + [a.purchase_cost for a, _ in flat]
    budget = scenario.constraints.budget_gbp
    units = _cost_units(amounts + ([] if budget is None else [budget]))
    capex = cp_model.LinearExpr.weighted_sum(
        [builds[c.candidate_id] for c in candidates] + [v for _, v in flat], units[: len(amounts)]
    )
    model.minimize(capex)
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    status = solver.solve(model)
    if status != cp_model.OPTIMAL:
        raise OptimizerFailure(OptimizerFailureCode.GLOBALLY_INFEASIBLE, solver.status_name(status))
    optimum = solver.value(capex)  # integer, never use float objective_value
    if budget is not None:
        if optimum > units[-1]:
            raise OptimizerFailure(
                OptimizerFailureCode.BUDGET_INFEASIBLE,
                f"{scenario.scenario_id}: minimum capex exceeds GBP {budget}",
            )
        model.add(capex <= units[-1])
    model.add(capex == optimum)
    # Lexicographic rank per canonically sorted demand, without huge weighted coefficients.
    for variables in choices:
        rank = cp_model.LinearExpr.weighted_sum(variables, list(range(len(variables))))
        model.minimize(rank)
        status = solver.solve(model)
        if status != cp_model.OPTIMAL:
            raise OptimizerFailure(
                OptimizerFailureCode.GLOBALLY_INFEASIBLE, f"tie-break: {solver.status_name(status)}"
            )
        model.add(rank == solver.value(rank))
    return [a for a, v in flat if solver.value(v)]


def optimize_candidate_network(scenario: PlanningScenario) -> OptimizationResult:
    """Return a validated plan and separate estimates; never mutate the input."""
    try:
        scenario = PlanningScenario.model_validate_json(scenario.model_dump_json())
        with localcontext() as context:
            context.prec = 100
            # Validate authoritative purchase amounts before Decimal multiplication could round.
            raw_costs = [c.estimated_build_cost_gbp for c in scenario.infrastructure_candidates]
            for option in scenario.fleet_options:
                if isinstance(option, RoadFleetOption):
                    raw_costs.append(option.vehicle.purchase_cost_gbp)
                else:
                    raw_costs.append(option.locomotive.purchase_cost_gbp)
                    raw_costs.extend(w.purchase_cost_gbp for w in option.wagon_options)
            _cost_units(raw_costs)
            chosen = _solve(scenario, _alternatives(scenario))
            plan = _emit(scenario, chosen)
            validate_execution_plan(plan, scenario)
            metrics = EstimatedPlanMetrics(
                schema_version=1,
                plan_hash=plan_hash(plan),
                estimator_name="candidate-network-optimizer",
                estimator_version="1",
                assumptions_digest=sha256(
                    canonical_bytes(scenario.economic_assumptions)
                ).hexdigest(),
                horizon_days=scenario.horizon_days,
                currency="GBP",
                predicted_delivered_cargo_units=sum(d.quantity for d in scenario.cargo_demands),
                infrastructure_spend_gbp=sum(
                    (a.estimated_build_cost_gbp for a in plan.infrastructure.actions), Decimal(0)
                ),
                vehicle_purchase_cost_gbp=sum((a.purchase_cost for a in chosen), Decimal(0)),
            )
            return OptimizationResult(plan, metrics)
    except (PlanningValidationError, ValidationError) as exc:
        raise OptimizerFailure(OptimizerFailureCode.UNSUPPORTED_SCENARIO, str(exc)) from exc
