"""Combine qualified bounded OD packages using the existing P08 road generator."""

from dataclasses import dataclass
from hashlib import sha256

from app.planning.canonical import world_manifest_hash
from app.planning.domain import (
    NetworkSelection,
    PlanningConstraints,
    PlanningScenario,
    ResourceLimit,
    ServiceResources,
    SourceReference,
    SupplyLimit,
)
from app.planning.p08_adapter import BoundedRoadInput, adapt_planning_facts
from app.planning.p08_road import ControlledRoadScenario, NoRoadScenario, generate_road_scenario
from app.simulation.openttd.supplemental_planning_facts import PlanningFactError

MAX_SERVICE_PACKAGES = 16


@dataclass(frozen=True)
class ControlledFreightNetwork:
    scenario: PlanningScenario
    services: tuple[ControlledRoadScenario, ...]
    rejected: tuple[NoRoadScenario, ...]
    classification: str = "CONTROLLED_MULTI_SERVICE_SCENARIO"
    native_execution_ready: bool = False


def generate_freight_network(
    inputs: tuple[BoundedRoadInput, ...],
    *,
    max_vehicles: int,
    resource_limits: tuple[ResourceLimit, ...] = (),
    allow_service_batches: bool = False,
) -> ControlledFreightNetwork:
    """One candidate OD per bounded package, all from the same qualified snapshot.

    Identical facilities are charged once. Partially overlapping corridors remain
    conflicting: the current executor has no incremental road-bit reuse contract.
    """
    if not 1 <= len(inputs) <= MAX_SERVICE_PACKAGES:
        raise PlanningFactError("network requires 1..16 bounded service packages")
    values = tuple(adapt_planning_facts(i.admitted, i.policy) for i in inputs)
    if values != inputs:
        raise PlanningFactError("conflicting adapter mapping/provenance")
    first = values[0]
    tiles, engines, coverage = {}, {}, {}
    for value in values:
        if (
            value.admitted.world.composition_digest != first.admitted.world.composition_digest
            or value.manifest != first.manifest
            or (
                value.policy != first.policy
                and (
                    not allow_service_batches
                    or value.policy.model_copy(
                        update={"delivery_batch_limit": first.policy.delivery_batch_limit}
                    )
                    != first.policy
                )
            )
            or value.facts.settings != first.facts.settings
            or value.facts.road != first.facts.road
            or value.facts.capture_economy_date_before != first.facts.capture_economy_date_before
            or value.facts.capture_economy_date_after != first.facts.capture_economy_date_after
        ):
            raise PlanningFactError(
                "network packages require one source, qualified month and policy"
            )
        for records, store, key in (
            (value.facts.tiles, tiles, lambda r: r.tile_id),
            (value.facts.engines, engines, lambda r: r.engine_id),
            (
                value.facts.coverage,
                coverage,
                lambda r: (r.tile_id, r.industry_id, r.cargo_id, r.role),
            ),
        ):
            for record in records:
                identity = key(record)
                if identity in store and store[identity] != record:
                    raise PlanningFactError("conflicting shared facts")
                store[identity] = record
    generated = tuple(
        generate_road_scenario(value, full_load_batch=allow_service_batches) for value in values
    )
    services = tuple(
        sorted(
            (r for r in generated if isinstance(r, ControlledRoadScenario)),
            key=lambda r: r.scenario.cargo_demands[0].demand_id,
        )
    )
    rejected = tuple(r for r in generated if isinstance(r, NoRoadScenario))
    if not services:
        raise PlanningFactError("no feasible bounded service candidates")
    digest = sha256("|".join(sorted({i.provenance.digest for i in values})).encode()).hexdigest()
    source = SourceReference(
        source_kind="p08-network-facts",
        source_id="qualified-batch",
        source_version="1",
        source_digest=digest,
    )
    locations, candidates, options, demands, sites, buildable = {}, {}, {}, {}, {}, {}

    def merge(store, key, record):
        if key in store and store[key] != record:
            raise PlanningFactError("conflicting shared candidate identity")
        store[key] = record

    for road in services:
        scenario = road.scenario
        for location in scenario.locations:
            normalized = location.model_copy(update={"source": source, "world_reference": None})
            merge(locations, location.location_id, normalized)
        for candidate in scenario.infrastructure_candidates:
            merge(
                candidates, candidate.candidate_id, candidate.model_copy(update={"source": source})
            )
        for option in scenario.fleet_options:
            merge(options, option.option_id, option.model_copy(update={"source": source}))
        for demand in scenario.cargo_demands:
            merge(demands, demand.demand_id, demand.model_copy(update={"source": source}))
        for site in scenario.world_manifest.resolved_sites:
            merge(sites, site.location_id, site)
        for tile in scenario.world_manifest.buildable_tiles:
            buildable[(tile.y, tile.x)] = tile
    manifest = first.manifest.model_copy(
        update={
            "resolved_sites": tuple(sites[k] for k in sorted(sites)),
            "cargo_types": tuple(sorted({d.cargo_type for d in demands.values()})),
            "vehicle_types": tuple(
                sorted({v for s in services for v in s.scenario.world_manifest.vehicle_types})
            ),
            "buildable_tiles": tuple(buildable[k] for k in sorted(buildable)),
        }
    )
    fingerprint = world_manifest_hash(manifest)
    # Keep industry references, now bound to the combined manifest.
    for road in services:
        for location in road.scenario.locations:
            if location.world_reference is not None:
                locations[location.location_id] = locations[location.location_id].model_copy(
                    update={
                        "world_reference": location.world_reference.model_copy(
                            update={"world_fingerprint": fingerprint}
                        )
                    }
                )
    cargos = {c.cargo_id: c.identifier for c in first.cargos}
    supply_limits = tuple(
        SupplyLimit(
            origin_id=f"industry-{s.industry_id}",
            cargo_type=cargos[s.cargo_id],
            quantity=s.quantity,
        )
        for s in first.supplies
        if (f"industry-{s.industry_id}", cargos[s.cargo_id])
        in {(d.origin_id, d.cargo_type) for d in demands.values()}
    )
    if len({r.scenario.cargo_demands[0].demand_id for r in services}) != len(services):
        raise PlanningFactError("duplicate OD service packages; supply must not be duplicated")
    combined = services[0].scenario.model_copy(
        update={
            "scenario_id": "controlled-p08-network",
            "scenario_version": "qualified-batch-network-v1",
            "world_manifest": manifest,
            "world_fingerprint": fingerprint,
            "locations": tuple(locations[k] for k in sorted(locations)),
            "infrastructure_candidates": tuple(candidates[k] for k in sorted(candidates)),
            "fleet_options": tuple(options[k] for k in sorted(options)),
            "cargo_demands": tuple(demands[k] for k in sorted(demands)),
            "constraints": PlanningConstraints(
                permitted_modes=services[0].scenario.constraints.permitted_modes,
                budget_gbp=first.policy.budget_gbp,
                network_selection=NetworkSelection(
                    supplies=supply_limits,
                    max_vehicles=max_vehicles,
                    resource_limits=resource_limits,
                    service_resources=tuple(
                        ServiceResources(
                            demand_id=r.scenario.cargo_demands[0].demand_id,
                            candidate_ids=tuple(
                                c.candidate_id for c in r.scenario.infrastructure_candidates
                            ),
                        )
                        for r in services
                    ),
                ),
            ),
        }
    )
    return ControlledFreightNetwork(
        PlanningScenario.model_validate_json(combined.model_dump_json()), services, rejected
    )
