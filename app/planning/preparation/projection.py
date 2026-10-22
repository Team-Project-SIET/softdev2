"""P08 publication boundary: canonical facts to existing unmodified P02/P06 contracts."""

from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from hashlib import sha256
from itertools import product

from pydantic import ValidationError

from app.planning.canonical import canonical_bytes, scenario_hash, world_manifest_hash
from app.planning.domain import (
    CargoDemand,
    ConstructionKind,
    EconomicAssumptions,
    InfrastructureCandidate,
    LocationKind,
    Mode,
    PlanningConstraints,
    PlanningLocation,
    PlanningScenario,
    PreparedWorldManifest,
    ResolvedSite,
    RoadFleetOption,
    SourceReference,
    Tile,
    VehicleDefinition,
    WorldReference,
)
from app.planning.execution import CatalogBinding, EngineBinding, ExecutionBindings
from app.planning.preparation.candidates import (
    FacilitySite,
    bound,
    depot_candidate,
    eligible,
    select_demand,
    station_candidates,
)
from app.planning.preparation.canonical import artifact_hash, authoritative, snapshot_hash
from app.planning.preparation.corridor import SearchBudget, search_corridors
from app.planning.preparation.costs import validate_cost_units
from app.planning.preparation.domain import (
    CandidateGenerationReport,
    ExtractedWorldSnapshot,
    PreparationBundle,
    PreparationProvenance,
    PreparationRequest,
)
from app.planning.preparation.failures import PreparationError, fail
from app.planning.preparation.failures import PreparationFailureCode as Code

DEFAULT_CARGO_LABELS = frozenset(
    {"PASS", "COAL", "MAIL", "OIL_", "LVST", "GOOD", "GRAI", "WOOD", "IORE", "STEL", "VALU"}
)


def validate_snapshot(world: ExtractedWorldSnapshot, request: PreparationRequest) -> None:
    source = world.prepared_save_digest
    profile = world.profile
    if (
        profile.openttd_version != "13.4"
        or profile.base_set_name != "OpenGFX"
        or profile.landscape != "temperate"
        or profile.newgrfs
        or profile.competing_active_companies
        or not profile.preparation_compatible
        or profile.road_type != 0
        or profile.catchment_radius != 3
        or profile.acceptance_threshold != 8
    ):
        fail(Code.UNSUPPORTED_WORLD, "profile", source, "world outside P08 v1 supported profile")
    if not world.complete:
        fail(Code.EXTRACTION_INCOMPLETE, "snapshot", source, "extraction lacks completion")
    if world.source_save_digest != request.expected_source_save_digest:
        fail(
            Code.WORLD_CHANGED_DURING_PREPARATION, "snapshot", source, "source save digest changed"
        )
    validate_cost_units(
        [world.road_build_cost_gbp, world.station_build_cost_gbp, world.depot_build_cost_gbp]
        + [e.purchase_cost_gbp for e in world.engines],
        source,
    )
    limits = request.limits
    size = world.width_tiles * world.height_tiles
    bound(size, limits.map_tiles, world, "snapshot", "map tiles")
    bound(len(world.industries), limits.industries, world, "snapshot", "industries")
    if len(world.tiles) != size or {t.tile_index for t in world.tiles} != set(range(size)):
        fail(
            Code.EXTRACTION_INCOMPLETE, "snapshot", source, "tile extraction is not complete/unique"
        )
    for values, attr in (
        (world.industries, "industry_id"),
        (world.cargos, "cargo_id"),
        (world.engines, "engine_id"),
    ):
        if len({getattr(v, attr) for v in values}) != len(values):
            fail(Code.CATALOG_IDENTITY_MISMATCH, "snapshot", source, "duplicate native identity")
    if len({c.label for c in world.cargos}) != len(world.cargos):
        fail(Code.CATALOG_IDENTITY_MISMATCH, "snapshot", source, "duplicate cargo label")
    if any(c.label not in DEFAULT_CARGO_LABELS for c in world.cargos):
        fail(Code.UNKNOWN_CARGO, "snapshot", source, "nondefault temperate cargo")
    cargo_ids = {c.cargo_id for c in world.cargos}
    industries = {i.industry_id: i for i in world.industries}
    tiles = {t.tile_index: t for t in world.tiles}
    for tile in world.tiles:
        if tile.tile_index != tile.y * world.width_tiles + tile.x or (
            tile.x >= world.width_tiles or tile.y >= world.height_tiles
        ):
            fail(Code.EXTRACTION_INCOMPLETE, "snapshot", source, "inconsistent tile coordinates")
        if tile.industry_id is not None and tile.industry_id not in industries:
            fail(Code.EXTRACTION_INCOMPLETE, "snapshot", source, "unresolved tile industry")
        if len({c.cargo_id for c in tile.cargo_facts}) != len(tile.cargo_facts):
            fail(Code.CATALOG_IDENTITY_MISMATCH, "snapshot", source, "duplicate tile cargo fact")
        if any(c.cargo_id not in cargo_ids for c in tile.cargo_facts):
            fail(Code.UNKNOWN_CARGO, "snapshot", source, "unresolved tile cargo")
    for industry in world.industries:
        if (
            industry.anchor_tile not in industry.footprint
            or len(set(industry.footprint)) != len(industry.footprint)
            or set(industry.footprint)
            != {t.tile_index for t in world.tiles if t.industry_id == industry.industry_id}
            or any(i not in tiles or tiles[i].occupancy != "industry" for i in industry.footprint)
        ):
            fail(Code.EXTRACTION_INCOMPLETE, "snapshot", source, "industry footprint mismatch")
        if len({c.cargo_id for c in industry.cargos}) != len(industry.cargos):
            fail(
                Code.CATALOG_IDENTITY_MISMATCH, "snapshot", source, "duplicate industry cargo fact"
            )
        if any(c.cargo_id not in cargo_ids for c in industry.cargos):
            fail(Code.UNKNOWN_CARGO, "snapshot", source, "unresolved industry cargo")
    if any(e.default_cargo_id not in cargo_ids for e in world.engines):
        fail(Code.UNKNOWN_CARGO, "snapshot", source, "unresolved engine default cargo")


def project_fleet(
    world: ExtractedWorldSnapshot, request: PreparationRequest, cargo_id: int
) -> tuple[tuple[RoadFleetOption, ...], ExecutionBindings]:
    cargo = next(c for c in world.cargos if c.cargo_id == cargo_id)
    options, engines = [], []
    extraction_digest = snapshot_hash(world)
    for engine in sorted(world.engines, key=lambda e: e.engine_id):
        if not (
            engine.freight
            and engine.immediately_buildable
            and not engine.articulated
            and not engine.refit_required
            and engine.default_cargo_id == cargo_id
            and engine.default_capacity > 0
            and engine.road_type == world.profile.road_type
            and engine.depot_class == "road"
        ):
            continue
        name = f"road-engine-{engine.engine_id}"
        with localcontext() as context:
            context.prec = 50
            daily = (engine.running_cost_gbp_per_year / Decimal(365)).quantize(
                Decimal("0.000001"), rounding=ROUND_HALF_EVEN
            )
        options.append(
            RoadFleetOption(
                option_id=f"fleet-{engine.engine_id}",
                mode=Mode.ROAD,
                vehicle=VehicleDefinition(
                    vehicle_type=name,
                    capacity_cargo_units=engine.default_capacity,
                    purchase_cost_gbp=engine.purchase_cost_gbp,
                    running_cost_gbp_per_day=daily,
                    speed_km_per_hour=Decimal(engine.native_speed_units) * Decimal("1.00584"),
                    compatible_cargo_types=(cargo.label,),
                ),
                road_vehicle_class="road",
                depot_class="road",
                available_from_day=0,
                available_through_day=0,
                source=SourceReference(
                    source_kind="p08-engine",
                    source_id=str(engine.engine_id),
                    source_version="p08-v1",
                    source_digest=extraction_digest,
                ),
            )
        )
        engines.append(
            EngineBinding(
                vehicle_type=name,
                engine_id=engine.engine_id,
                engine_name=engine.name,
                mode=Mode.ROAD,
                road_type=engine.road_type,
                road_station_kind="truck",
            )
        )
    bound(len(options), request.limits.fleet_options, world, "fleet", "fleet options")
    if not options:
        fail(
            Code.FLEET_CATALOG_UNAVAILABLE,
            "fleet",
            world.prepared_save_digest,
            "no immediately buildable default-cargo freight engine",
        )
    return tuple(options), ExecutionBindings(
        engines=tuple(engines),
        cargo_ids=(
            CatalogBinding(
                identifier=cargo.label, runtime_id=cargo.cargo_id, runtime_name=cargo.label
            ),
        ),
        rail_types=(),
    )


def validate_candidate_limits(
    scenario: PlanningScenario, request: PreparationRequest, world: ExtractedWorldSnapshot
) -> None:
    """Hard output bounds apply before any candidate-space compatibility proof."""
    limits = request.limits
    candidates = scenario.infrastructure_candidates
    locations = {site.location_id: site for site in scenario.locations}
    bound(len(scenario.cargo_demands), limits.demands, world, "projection", "mandatory demands")
    bound(len(scenario.fleet_options), limits.fleet_options, world, "projection", "fleet options")
    bound(
        len(candidates),
        limits.infrastructure_candidates,
        world,
        "projection",
        "infrastructure candidates",
    )
    bound(
        sum(c.kind is ConstructionKind.DEPOT for c in candidates),
        limits.depots,
        world,
        "projection",
        "depots",
    )
    roles, pairs = {}, {}
    for c in candidates:
        if c.kind is ConstructionKind.STATION:
            if c.site_id is None or c.site_id not in locations:
                fail(
                    Code.INVALID_PREPARATION_OUTPUT,
                    "projection",
                    world.prepared_save_digest,
                    "station candidate site is unresolved",
                )
            role = locations[c.site_id].serves_location_id
            roles[role] = roles.get(role, 0) + 1
        elif c.kind is ConstructionKind.SEGMENT:
            pair = (c.origin_id, c.destination_id)
            pairs[pair] = pairs.get(pair, 0) + 1
            bound(len(c.tiles), limits.corridor_length, world, "projection", "corridor length")
    for count in roles.values():
        bound(count, limits.stations_per_role, world, "projection", "station candidates per role")
    for count in pairs.values():
        bound(count, limits.corridors_per_pair, world, "projection", "corridors per directed pair")
    bound(
        len(canonical_bytes(scenario)),
        limits.scenario_bytes,
        world,
        "projection",
        "canonical scenario bytes",
    )


def prepare_world(
    request: PreparationRequest, snapshot: ExtractedWorldSnapshot
) -> PreparationBundle:
    """Publish only a fully canonical, bounded, combination-safe preparation bundle."""
    try:
        request = authoritative(request)
        world = authoritative(snapshot)
        validate_snapshot(world, request)
        demand, relation_count = select_demand(world, request)
        industries = {i.industry_id: i for i in world.industries}
        origin, destination = industries[demand.origin_id], industries[demand.destination_id]
        pickups, pickup_report = station_candidates(
            world, request, origin, demand.cargo_id, "pickup"
        )
        deliveries, delivery_report = station_candidates(
            world, request, destination, demand.cargo_id, "delivery"
        )
        reserved = frozenset(s.tile_index for s in (*pickups, *deliveries))
        depot = depot_candidate(world, reserved, (*pickups, *deliveries))
        budget = SearchBudget()
        corridor_rows = []
        for pickup, delivery in product(pickups, deliveries):
            try:
                paths = search_corridors(
                    world,
                    request,
                    pickup,
                    delivery,
                    depot.front_tile,
                    reserved | {depot.tile_index},
                    budget,
                )
            except PreparationError as error:
                if error.code in {Code.NO_FEASIBLE_CORRIDOR, Code.UNSUPPORTED_TERRAIN}:
                    continue
                raise
            for path in paths:
                corridor_rows.append((pickup, delivery, path))
        if not corridor_rows:
            fail(
                Code.NO_FEASIBLE_CORRIDOR,
                "corridors",
                world.prepared_save_digest,
                "no sampled station pair has a supported shared-anchor corridor",
            )
        fleet, bindings = project_fleet(world, request, demand.cargo_id)
        bindings = authoritative(bindings)
        source = SourceReference(
            source_kind="p08-preparation",
            source_id=request.scenario_id,
            source_version="p08-v1",
            source_digest=artifact_hash(request),
        )
        locations, candidates = [], []

        def tile(index: int) -> Tile:
            return Tile(x=index % world.width_tiles, y=index // world.width_tiles)

        for role, industry in (("origin", origin), ("destination", destination)):
            locations.append(
                PlanningLocation(
                    location_id=role,
                    tile=tile(industry.anchor_tile),
                    kind=LocationKind.INDUSTRY_ORIGIN
                    if role == "origin"
                    else LocationKind.INDUSTRY_DESTINATION,
                    permitted_modes=(Mode.ROAD,),
                    source=source,
                )
            )

        def facility(name: str, site: FacilitySite, serves: str | None) -> None:
            is_depot = serves is None
            locations.append(
                PlanningLocation(
                    location_id=name,
                    tile=tile(site.tile_index),
                    kind=LocationKind.DEPOT_CANDIDATE
                    if is_depot
                    else LocationKind.STATION_CANDIDATE,
                    permitted_modes=(Mode.ROAD,),
                    footprint_width_tiles=1,
                    footprint_height_tiles=1,
                    orientation=site.orientation,
                    serves_location_id=serves,
                    facility_class="road" if is_depot else "truck",
                    source=source,
                )
            )
            candidates.append(
                InfrastructureCandidate(
                    candidate_id=f"build-{name}",
                    mode=Mode.ROAD,
                    kind=ConstructionKind.DEPOT if is_depot else ConstructionKind.STATION,
                    site_id=name,
                    footprint_width_tiles=1,
                    footprint_height_tiles=1,
                    orientation=site.orientation,
                    estimated_build_cost_gbp=world.depot_build_cost_gbp
                    if is_depot
                    else world.station_build_cost_gbp,
                    source=source,
                )
            )

        for sites, role in ((pickups, "origin"), (deliveries, "destination")):
            for site in sites:
                facility(f"{role}-stop-{site.tile_index}", site, role)
        facility("shared-depot", depot, None)
        for pickup, delivery, path in corridor_rows:
            digest = sha256(",".join(map(str, path)).encode()).hexdigest()[:24]
            candidates.append(
                InfrastructureCandidate(
                    candidate_id=f"corridor-{digest}",
                    mode=Mode.ROAD,
                    kind=ConstructionKind.SEGMENT,
                    origin_id=f"origin-stop-{pickup.tile_index}",
                    destination_id=f"destination-stop-{delivery.tile_index}",
                    tiles=tuple(tile(i) for i in path),
                    estimated_build_cost_gbp=world.road_build_cost_gbp * len(path),
                    source=source,
                )
            )
        bound(
            len(candidates),
            request.limits.infrastructure_candidates,
            world,
            "projection",
            "infrastructure candidates",
        )
        sites = []
        for location in locations:
            site = ResolvedSite.model_validate(
                location.model_dump(exclude={"source", "world_reference"})
            )
            if location.location_id in {"origin", "destination"}:
                site = site.model_copy(
                    update={
                        "world_kind": "industry",
                        "world_id": origin.industry_id
                        if location.location_id == "origin"
                        else destination.industry_id,
                    }
                )
            sites.append(site)
        cargo = next(c for c in world.cargos if c.cargo_id == demand.cargo_id)
        manifest = authoritative(
            PreparedWorldManifest(
                schema_version=1,
                source_digest=world.prepared_save_digest,
                openttd_version=world.profile.openttd_version,
                base_set_name=world.profile.base_set_name,
                base_set_version=world.profile.base_set_version,
                width_tiles=world.width_tiles,
                height_tiles=world.height_tiles,
                seed=world.seed,
                resolved_sites=tuple(sites),
                cargo_types=(cargo.label,),
                vehicle_types=tuple(o.vehicle.vehicle_type for o in fleet),
                buildable_tiles=tuple(tile(t.tile_index) for t in world.tiles if eligible(t)),
            )
        )
        fingerprint = world_manifest_hash(manifest)
        locations = [
            location.model_copy(
                update={
                    "world_reference": WorldReference(
                        world_fingerprint=fingerprint,
                        kind="industry",
                        world_id=origin.industry_id
                        if location.location_id == "origin"
                        else destination.industry_id,
                    )
                }
            )
            if location.location_id in {"origin", "destination"}
            else location
            for location in locations
        ]
        scenario = authoritative(
            PlanningScenario(
                schema_version=1,
                scenario_id=request.scenario_id,
                scenario_version="p08-v1",
                world_fingerprint=fingerprint,
                world_manifest=manifest,
                openttd_version=manifest.openttd_version,
                base_set_name=manifest.base_set_name,
                base_set_version=manifest.base_set_version,
                width_tiles=world.width_tiles,
                height_tiles=world.height_tiles,
                seed=world.seed,
                start_date=world.preparation_date,
                horizon_days=request.horizon_days,
                supported_modes=(Mode.ROAD,),
                locations=tuple(locations),
                cargo_demands=(
                    CargoDemand(
                        demand_id="historical-demand",
                        cargo_type=cargo.label,
                        origin_id="origin",
                        destination_id="destination",
                        quantity=demand.quantity,
                        unit="cargo_units",
                        earliest_day=0,
                        latest_delivery_day=demand.latest_delivery_day,
                        priority="normal",
                        max_transit_days=None,
                        source=SourceReference(
                            source_kind="p08-demand-policy",
                            source_id="native-origin-cargo-destination-order-v1",
                            source_version="p08-v1",
                            source_digest=artifact_hash(request),
                        ),
                    ),
                ),
                fleet_options=fleet,
                infrastructure_candidates=tuple(candidates),
                economic_assumptions=EconomicAssumptions(
                    currency="GBP", model_name="native-flat-road", model_version="1"
                ),
                constraints=PlanningConstraints(permitted_modes=(Mode.ROAD,)),
            )
        )
        validate_candidate_limits(scenario, request, world)
        from app.planning.preparation.safety import check_combination_safety

        check_combination_safety(scenario, bindings, world)
        report = authoritative(
            CandidateGenerationReport(
                relationships_examined=relation_count,
                station_sampling=(pickup_report, delivery_report),
                depot_tile=depot.tile_index,
                depot_front=depot.front_tile,
                search_expansions=budget.expansions,
                corridor_count=len(corridor_rows),
            )
        )
        from app.planning.preparation.probe import probe_package_hash

        provenance = authoritative(
            PreparationProvenance(
                request_hash=artifact_hash(request),
                probe_package_hash=probe_package_hash(),
                source_save_digest=world.source_save_digest,
                prepared_save_digest=world.prepared_save_digest,
                snapshot_hash=snapshot_hash(world),
                candidate_report_hash=artifact_hash(report),
                manifest_hash=fingerprint,
                scenario_hash=scenario_hash(scenario),
                bindings_hash=artifact_hash(bindings),
            )
        )
        return PreparationBundle(
            request=request,
            snapshot=world,
            report=report,
            manifest=manifest,
            scenario=scenario,
            bindings=bindings,
            provenance=provenance,
            provenance_hash=artifact_hash(provenance),
        )
    except ValidationError as error:
        fail(
            Code.EXTRACTION_INCOMPLETE,
            "strict-parse",
            snapshot.prepared_save_digest,
            "strict extraction/preparation contract rejected",
        )
        raise AssertionError("unreachable") from error
