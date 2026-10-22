"""Opt-in controlled P05 comparisons over a retained P08 scenario."""

import json
from decimal import Decimal

from app.planning.canonical import scenario_hash
from app.planning.domain import PlanningScenario
from app.planning.optimizer import OptimizerFailure, optimize_candidate_network
from app.planning.validation import validate_execution_plan


def compare_freight_alternatives(scenario: PlanningScenario) -> dict:
    """Compare explicit assumptions; never calibrate defaults or predict native gains."""
    if scenario.constraints.network_selection is None:
        raise ValueError("controlled comparison requires P08 network-selection inputs")
    baseline = scenario.model_dump(mode="json")
    variants = [("baseline", "Retained P08 planning inputs.", {})]
    variants.extend(
        [
            ("fleet_limit_6", "Allow six vehicles; demand stays unchanged.", {"limit": 6}),
            (
                "capacity_10",
                "Hypothetical ten-unit engine at unchanged price/speed.",
                {"capacity": 10, "limit": 6},
            ),
            (
                "capacity_40",
                "Hypothetical forty-unit engine at unchanged price/speed.",
                {"capacity": 40},
            ),
            (
                "demand_40_limit_3",
                "Supplied demand becomes forty per service; three vehicles.",
                {"demand": 40},
            ),
            (
                "demand_40_limit_6",
                "Supplied demand becomes forty per service; six vehicles.",
                {"demand": 40, "limit": 6},
            ),
            (
                "infrastructure_double_cost",
                "Same infrastructure candidates at twice estimated cost.",
                {"cost_multiplier": 2},
            ),
        ]
    )
    variants.extend(
        (
            f"extra_vehicle_service_{index}",
            f"Forty units supplied for {demand.demand_id}; twenty for others; four vehicles.",
            {"extra_service": demand.demand_id, "limit": 4},
        )
        for index, demand in enumerate(scenario.cargo_demands)
    )
    rows = []
    for name, assumption, changes in variants:
        value = scenario.model_dump(mode="json")
        if "limit" in changes:
            value["constraints"]["network_selection"]["max_vehicles"] = changes["limit"]
        for option in value["fleet_options"]:
            if "capacity" in changes:
                if option["mode"] != "road":
                    raise ValueError("capacity variants require road fleet options")
                option["vehicle"]["capacity_cargo_units"] = changes["capacity"]
        for demand in value["cargo_demands"]:
            if "demand" in changes:
                demand["quantity"] = changes["demand"]
            elif demand["demand_id"] == changes.get("extra_service"):
                demand["quantity"] = 40
        for candidate in value["infrastructure_candidates"]:
            candidate["estimated_build_cost_gbp"] = str(
                Decimal(candidate["estimated_build_cost_gbp"]) * changes.get("cost_multiplier", 1)
            )
        variant = PlanningScenario.model_validate_json(json.dumps(value))
        row = dict(name=name, assumption=assumption, scenario_digest=scenario_hash(variant))
        try:
            result = optimize_candidate_network(variant)
        except OptimizerFailure as error:
            row.update(feasible=False, failure_code=error.code.value)
        else:
            validate_execution_plan(result.plan, variant)
            quantities = {d.demand_id: d.quantity for d in variant.cargo_demands}
            groups = result.plan.fleet.groups
            infrastructure = sum(
                (a.estimated_build_cost_gbp for a in result.plan.infrastructure.actions), Decimal(0)
            )
            purchase = result.metrics.vehicle_purchase_cost_gbp
            assert purchase is not None
            row.update(
                feasible=True,
                independently_validated=True,
                served_planning_units=sum(quantities[d] for g in groups for d in g.demand_ids),
                vehicles=sum(g.count for g in groups),
                allocation={d: g.count for g in groups for d in g.demand_ids},
                estimated_infrastructure_gbp=str(infrastructure),
                estimated_vehicle_purchase_gbp=str(purchase),
                estimated_capex_gbp=str(infrastructure + purchase),
                planned_trips_per_vehicle=sorted({g.planned_trips_per_vehicle for g in groups}),
            )
        rows.append(row)
    assert scenario.model_dump(mode="json") == baseline
    return dict(
        classification="CONTROLLED_P08_P05_ALTERNATIVES",
        native_launches=0,
        admin_connections=0,
        objective="unchanged P05: maximize supplied cargo, then minimize CAPEX",
        baseline_scenario_digest=scenario_hash(scenario),
        limitations=[
            "Feasible means validated planning constraints, not native execution readiness.",
            "Planning units are one-trip demand, not monthly or annual throughput predictions.",
            "Capacity variants are hypothetical; only the twenty-unit engine was observed.",
            "Frequency is unsupported: P05 emits one trip per vehicle, with no recurring schedule.",
            "Extra vehicles are allocations, not proven frequency or delivery improvements.",
            "Variant service indices follow scenario demand order, not P07 chart order; "
            "use the assumption and allocation demand identifiers.",
            "Cost sensitivity retains geometry; physical upgrades need new P08 candidates/facts.",
            "No OPEX, profit, ROI or native performance improvement is estimated.",
        ],
        rows=rows,
    )


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", type=Path)
    args = parser.parse_args()
    retained = PlanningScenario.model_validate_json(args.scenario.read_bytes())
    print(json.dumps(compare_freight_alternatives(retained), indent=2))
