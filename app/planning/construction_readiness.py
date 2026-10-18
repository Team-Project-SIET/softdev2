"""Construction readiness assessment for bounded P08 terrain outcomes (Task C).

This is a *readiness* registry, not an executable construction package: every
entry states the native API seam, preconditions, expected tile/neighbor
effects, cost provenance, partial-failure risk and post-command readbacks for
one modification class, and names what still blocks native execution. Entries
derive only from verified 15.3 source facts and the implemented planning
contracts; nothing here invents bridges, tunnels, demolition permissions or
native terraform success.
"""

from dataclasses import dataclass

from app.planning.p08_terrain import (
    CAPEX_CATEGORY_TERRAIN,
    MAX_TERRAIN_HEIGHT_DELTA_STEPS,
    SegmentClass,
    TerrainOp,
)

NATIVE_SUPPORT_EXECUTED = "NATIVELY_EXECUTED_IN_FIXED_PATH"
NATIVE_SUPPORT_PACKAGE_READY = "PACKAGE_READY_PENDING_AUTHORIZATION"
NATIVE_SUPPORT_NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
NATIVE_SUPPORT_PROHIBITED = "PROHIBITED_IN_PROPOSALS"
NATIVE_SUPPORT_OUT_OF_SCOPE = "OUT_OF_SCOPE"


@dataclass(frozen=True)
class ConstructionRequirement:
    """One construction-operation readiness record (no live execution)."""

    requirement_id: str
    covered_segment_class: str
    native_api: str
    preconditions: tuple[str, ...]
    expected_tile_changes: str
    neighboring_effects: str
    cost_provenance: str
    partial_failure_risks: str
    post_command_readbacks: tuple[str, ...]
    native_support: str
    existing_native_evidence: str
    missing_implementation: str
    capex_category: str = CAPEX_CATEGORY_TERRAIN


BUILD_ROAD = ConstructionRequirement(
    requirement_id="BUILD_ROAD",
    covered_segment_class=SegmentClass.ROAD_BUILDABLE.value,
    native_api=(
        "GSRoad.BuildRoad(start, end) under GSCompanyMode; "
        "GSRoad.IsRoadTypeAvailable/SetCurrentRoadType first"
    ),
    preconditions=(
        "both tiles vacant flat clear ground (GSTile.IsBuildable, GetSlope==0, owner invalid, "
        "no water/coast/tree/farm/rock/rough/transport)",
        "equal GSTile.GetMinHeight on both tiles",
        "road path stays inside the 2..47 road-tile admission",
        "typed execution plan admitted by P05 (P08 supplies candidates only)",
    ),
    expected_tile_changes="two to forty-seven MP_ROAD tiles with depots/stations built separately",
    neighboring_effects="none beyond the built road path (no terraform cascades)",
    cost_provenance=(
        "GSAccounting() in test mode (GetCosts) billed at exec; no offline price inference"
    ),
    partial_failure_risks="command fails closed without partial road application on the flat path",
    post_command_readbacks=(
        "GSRoad.IsRoadTile per built tile",
        "GSRoad.AreRoadTilesConnected both directions",
        "GSTile.GetOwner",
    ),
    native_support=NATIVE_SUPPORT_EXECUTED,
    existing_native_evidence=(
        "fixed demo package (freight_delivery_package network/planner .nut) builds roads under "
        "GSCompanyMode; the retained Seed 17 attempt left this path NOT_RUN"
    ),
    missing_implementation=(
        "none for the fixed bounded path; terrain-proposal integration is planning-only"
    ),
)

CLASSIFIED_CLEAR = ConstructionRequirement(
    requirement_id="CLASSIFIED_CLEAR",
    covered_segment_class=SegmentClass.SUPPORTED_CLEARING.value,
    native_api="GSTile.DemolishTile(tile) (CMD_LANDSCAPE_CLEAR) from deity or company mode",
    preconditions=(
        "native occupancy classified as trees/rough/rocks/fields (schema-2 flags or projected "
        "TileFact ground flags)",
        "no prior mutation on shared corner points (clear precedes corner writes per host tile)",
        "GSTileDemolishTile return checked; company mode requires town-rating headroom unknowns",
    ),
    expected_tile_changes=(
        "tile becomes MP_CLEAR grass retaining its current slope and corner heights"
    ),
    neighboring_effects="none documented by the 15.3 API for single-tile demolition",
    cost_provenance=(
        "GSAccounting() in test mode; GetBuildCost clearing classes never invented offline"
    ),
    partial_failure_risks=(
        "demolition of occupied tiles can fail on ownership/permissions; the command either "
        "clears the tile or fails, no partial tile state documented"
    ),
    post_command_readbacks=(
        "GSTile.IsBuildable",
        "GSTile.GetSlope",
        "GSTile.HasTreeOnTile/IsRoughTile/IsRockTile/IsFarmTile negated",
        "GSTile.GetOwner",
    ),
    native_support=NATIVE_SUPPORT_EXECUTED,
    existing_native_evidence=(
        "fixed-path .nut clears non-vacant tiles with GSTile.DemolishTile before road construction "
        "(freight_delivery_package); retained Seed 17 terrain proposals never executed a clear"
    ),
    missing_implementation="no staged path issues DemolishTile for terrain proposals yet",
)

CORNER_RAISE = ConstructionRequirement(
    requirement_id="CORNER_RAISE",
    covered_segment_class=SegmentClass.TERRAIN_MODIFICATION.value,
    native_api=(
        "GSTile.RaiseTile(tile, slope_mask) (CMD_TERRAFORM_LAND, corners W,S,E,N) "
        "under GSCompanyMode"
    ),
    preconditions=(
        "tile corner heights differ from the proposal target by exactly "
        f"{MAX_TERRAIN_HEIGHT_DELTA_STEPS} step in the raise direction",
        "shared corner points written once (disambiguated host tile per point)",
        "no forbidden/native footprint inside the shared-corner region closure",
        "all closures observed: no corner written onto tiles missing from the capture",
        "region/halo within the typed budgets (32 corner ops, 128 region tiles)",
    ),
    expected_tile_changes="raised corners +1 height step; the tile is MP_CLEAR ground afterwards",
    neighboring_effects=(
        "the command can raise/remove neighboring corners (documented cascading in the 15.3 "
        "terraform layer); every region and halo tile therefore needs post-run readbacks"
    ),
    cost_provenance=(
        "GetBuildCost(BT_TERRAFORM) and GSAccounting at runtime only; offline cost stays None"
    ),
    partial_failure_risks=(
        "ERR_AREA_NOT_CLEAR / ERR_TOO_CLOSE_TO_EDGE / ERR_TILE_TOO_HIGH|LOW can stop partway with "
        "earlier corners of the same command already applied (multi-corner masks are not atomic)"
    ),
    post_command_readbacks=(
        "GSTile.GetCornerHeight per region and halo tile",
        "GSTile.GetMinHeight",
        "GSTile.GetSlope",
        "GSTile.GetCargoAcceptance / GetCargoProduction for covered stop tiles",
    ),
    native_support=NATIVE_SUPPORT_NOT_IMPLEMENTED,
    existing_native_evidence=(
        "no staged package issues RaiseTile; retained proposals are planning-only"
    ),
    missing_implementation=(
        "a reviewed staged terrain-execution package plus one authorization with corner-readback "
        "receipts; planning contracts ready"
    ),
)

CORNER_LOWER = ConstructionRequirement(
    requirement_id="CORNER_LOWER",
    covered_segment_class=SegmentClass.TERRAIN_MODIFICATION.value,
    native_api=(
        "GSTile.LowerTile(tile, slope_mask) (CMD_TERRAFORM_LAND, corners W,S,E,N) "
        "under GSCompanyMode"
    ),
    preconditions=CORNER_RAISE.preconditions,
    expected_tile_changes="lowered corners -1 height step; the tile is MP_CLEAR ground afterwards",
    neighboring_effects=CORNER_RAISE.neighboring_effects,
    cost_provenance=CORNER_RAISE.cost_provenance,
    partial_failure_risks=(
        "ERR_AREA_NOT_CLEAR / ERR_TOO_CLOSE_TO_EDGE / ERR_TILE_TOO_HIGH|LOW can stop partway with "
        "earlier corners of the same command already applied (multi-corner masks are not atomic)"
    ),
    post_command_readbacks=CORNER_RAISE.post_command_readbacks,
    native_support=NATIVE_SUPPORT_NOT_IMPLEMENTED,
    existing_native_evidence=(
        "no staged package issues LowerTile; retained proposals are planning-only"
    ),
    missing_implementation=CORNER_RAISE.missing_implementation,
)

LEVEL_TILES = ConstructionRequirement(
    requirement_id="LEVEL_TILES",
    covered_segment_class=SegmentClass.TERRAIN_MODIFICATION.value,
    native_api="GSTile.LevelTiles(start, end) (CMD_LEVEL_LAND)",
    preconditions=("- not admissible: prohibited in every proposal",),
    expected_tile_changes="undefined for proposals because partial application is documented",
    neighboring_effects="undefined for proposals (command may apply before failing)",
    cost_provenance="n/a while prohibited",
    partial_failure_risks=(
        "15.3 documents partial application on failure and divergence between ScriptTestMode "
        "(return true) and ScriptExecMode (fail); such semantics cannot support staged proposals"
    ),
    post_command_readbacks=("GSTile.GetCornerHeight to detect partial application",),
    native_support=NATIVE_SUPPORT_PROHIBITED,
    existing_native_evidence="never used in this project's staged packages",
    missing_implementation="deliberately none: prohibition is by contract, not by omission",
)

OCCUPANCY_CONVERSION = ConstructionRequirement(
    requirement_id="OCCUPANCY_CONVERSION",
    covered_segment_class=SegmentClass.UNSUPPORTED_CONSTRUCTION.value,
    native_api=(
        "unverified: would involve demolishing/converting houses, stations, "
        "industry, road, rail, dock or airport footprints"
    ),
    preconditions=(
        "- not admissible offline: the retained facts do not establish any conversion permission, "
        "company ownership or town-rating consequence; schema-2 evidence required first"
    ),
    expected_tile_changes="documented only after a separately authorized observation",
    neighboring_effects="unknown (station/house adjacency effects unverified)",
    cost_provenance="UNKNOWN until observed (never inferred)",
    partial_failure_risks="unknown",
    post_command_readbacks=("full schema-2 re-classification of the touched footprint",),
    native_support=NATIVE_SUPPORT_OUT_OF_SCOPE,
    existing_native_evidence=(
        "the wire retains house/station bits but the schema-1 TileFact projection drops them; "
        "the classification schema (2) exists as an additive contract "
        "awaiting an authorized capture"
    ),
    missing_implementation=(
        "classification capture, then a separately reviewed construction contract"
    ),
)

UNKNOWN_TILE = ConstructionRequirement(
    requirement_id="UNKNOWN_TILE",
    covered_segment_class=SegmentClass.UNKNOWN_OCCUPANCY.value,
    native_api="none (classification unavailable)",
    preconditions=(
        "schema-2 capture required; retained Seed 17 evidence drops the occupancy class for "
        "19 relevant tiles and no other field may recover it",
    ),
    expected_tile_changes="not determinable offline",
    neighboring_effects="not determinable offline",
    cost_provenance="UNKNOWN",
    partial_failure_risks="not determinable offline",
    post_command_readbacks=("not determinable offline",),
    native_support=NATIVE_SUPPORT_NOT_IMPLEMENTED,
    existing_native_evidence="none",
    missing_implementation=(
        "schema-2 classification capture (tile_classification_page) under fresh authorization"
    ),
)

_BUCKET: dict[str, str] = {
    "raise": CORNER_RAISE.requirement_id,
    "lower": CORNER_LOWER.requirement_id,
    "clear": CLASSIFIED_CLEAR.requirement_id,
}


def requirement_for_op(op: TerrainOp) -> str:
    """Map a planning-only terrain op to its readiness record id."""
    if op.kind not in _BUCKET:
        raise ValueError(f"unsupported terrain op kind: {op.kind!r}")
    return _BUCKET[op.kind]


CLASSIFIED_OBSTACLE_REQUIREMENTS: dict[str, str] = {
    "TREES": CLASSIFIED_CLEAR.requirement_id,
    "FARM": CLASSIFIED_CLEAR.requirement_id,
    "ROCK": CLASSIFIED_CLEAR.requirement_id,
    "ROUGH": CLASSIFIED_CLEAR.requirement_id,
    "HOUSE": OCCUPANCY_CONVERSION.requirement_id,
    "STATION": OCCUPANCY_CONVERSION.requirement_id,
    "INDUSTRY": OCCUPANCY_CONVERSION.requirement_id,
    "AIRPORT": OCCUPANCY_CONVERSION.requirement_id,
    "DOCK": OCCUPANCY_CONVERSION.requirement_id,
    "ROAD": OCCUPANCY_CONVERSION.requirement_id,
    "RAIL": OCCUPANCY_CONVERSION.requirement_id,
    "WATER": OCCUPANCY_CONVERSION.requirement_id,
    "COAST": OCCUPANCY_CONVERSION.requirement_id,
    "UNKNOWN_OCCUPANCY": UNKNOWN_TILE.requirement_id,
}


def requirement_for_tile_class(tile_class: str, *, slope: int = 0) -> str:
    """Map one schema-2 classification to its construction readiness record.

    CLEAR is shape-dependent: flat clear ground belongs to the executed
    BUILD_ROAD path, sloped clear ground to the planning-only terrain
    modification records. Every other class has one requirement; unknown ids
    and unknown classes are rejected instead of being bucketed silently.
    """
    if tile_class == "CLEAR":
        return CORNER_RAISE.requirement_id if slope else BUILD_ROAD.requirement_id
    try:
        return CLASSIFIED_OBSTACLE_REQUIREMENTS[tile_class]
    except KeyError as e:
        raise ValueError(f"unclassified tile class: {tile_class!r}") from e


def classification_readiness_report(class_counts: dict[str, int]) -> list[dict]:
    """Machine-readable per-classified-obstacle readiness projection.

    For the census class distribution the report gives the owning readiness
    record, its native support statement and whether the construction path is
    planning-only. CLEAR is shape-dependent and therefore projected for both
    a flat and a sloped segment; no entry converts a planning proposal into
    an executable native command.
    """
    report: list[dict] = []
    for tile_class in sorted(class_counts):
        requirement_id = requirement_for_tile_class(tile_class)
        record = readiness_summary(requirement_id)
        if tile_class == "CLEAR":
            for shape, slope in (
                ("flat", 0),
                ("sloped", 1),
            ):
                shaped_id = requirement_for_tile_class(tile_class, slope=slope)
                shaped_record = readiness_summary(shaped_id)
                report.append(
                    {
                        "tile_class": tile_class,
                        "shape": shape,
                        "requirement_id": shaped_id,
                        "native_api": shaped_record.native_api,
                        "native_support": shaped_record.native_support,
                        "planning_only": shaped_record.native_support
                        not in (NATIVE_SUPPORT_EXECUTED,),
                    }
                )
            continue
        report.append(
            {
                "tile_class": tile_class,
                "requirement_id": requirement_id,
                "native_api": record.native_api,
                "native_support": record.native_support,
                "planning_only": record.native_support not in (NATIVE_SUPPORT_EXECUTED,),
            }
        )
    return report


def requirement_ids_for_counts(
    corridor_segment_counts: tuple[tuple[str, int], ...],
) -> tuple[str, ...]:
    """Deterministic readiness ids for the segment classes along a corridor."""
    order = (
        (SegmentClass.ROAD_BUILDABLE.value, BUILD_ROAD.requirement_id),
        (SegmentClass.SUPPORTED_CLEARING.value, CLASSIFIED_CLEAR.requirement_id),
        (SegmentClass.TERRAIN_MODIFICATION.value, CORNER_RAISE.requirement_id),
        (SegmentClass.UNSUPPORTED_CONSTRUCTION.value, OCCUPANCY_CONVERSION.requirement_id),
        (SegmentClass.UNKNOWN_OCCUPANCY.value, UNKNOWN_TILE.requirement_id),
    )
    present = dict(corridor_segment_counts)
    return tuple(rid for segment, rid in order if present.get(segment))


def readiness_summary(requirement_id: str) -> ConstructionRequirement:
    """Fail explicit if a readiness record is requested by unknown id."""
    for record in (
        BUILD_ROAD,
        CLASSIFIED_CLEAR,
        CORNER_RAISE,
        CORNER_LOWER,
        LEVEL_TILES,
        OCCUPANCY_CONVERSION,
        UNKNOWN_TILE,
    ):
        if record.requirement_id == requirement_id:
            return record
    raise ValueError(f"unknown construction requirement: {requirement_id!r}")


def blocked_offline() -> tuple[str, ...]:
    """Exact blockers standing between contracts and native execution."""
    return (
        "no fresh authorization (the Seed 17 one-shot is consumed)",
        "no staged package issues RaiseTile/LowerTile; partial-apply behavior of multi-corner "
        "CMD_TERRAFORM_LAND masks is documented but unverified natively",
        "native house/station/industry conversion permissions are unverified "
        "(schema-2 classification capture pending)",
        "GetBuildCost(BT_TERRAFORM) spend is UNKNOWN until observed",
    )
